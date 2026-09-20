"""
Fetching a library from GitHub.

Only the files the manifest actually lists are downloaded. GitHub can only hand
out a zip of an entire repository, so the zip is avoided: the manifest is read
first, then each listed file is fetched on its own. For a library whose repo
carries a vendored test framework, that is the difference between a few hundred
kilobytes and a few.
"""

import json
import shutil
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from . import manifest, yamlreader

RAW_URL = "https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}"
TREE_URL = "https://api.github.com/repos/{owner}/{repo}/git/trees/{ref}?recursive=1"
DEFAULT_OWNER = "nimaltd"
TIMEOUT_SECONDS = 30


class DownloadError(Exception):
    """A library could not be fetched, with a reason worth showing the user."""


def _fetch(owner, repo, ref, path):
    """Fetch one file's bytes. Raises DownloadError with a readable message."""
    url = RAW_URL.format(owner=owner, repo=repo, ref=ref, path=path)

    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise DownloadError(f"{path} does not exist in {owner}/{repo} at {ref}.") from error
        raise DownloadError(f"Could not download {url}: HTTP {error.code}.") from error
    except urllib.error.URLError as error:
        raise DownloadError(f"Could not reach GitHub: {error.reason}.") from error


def _listed_entries(data):
    """
    Every repository path or pattern a parsed manifest refers to.

    A files entry is either a plain path, a folder, a wildcard, or a
    {from, to} pair, and only the "from" side names something to download.
    """
    files = data.get("files") or {}
    listed = list(files.get("headers") or []) + list(files.get("sources") or [])
    listed += data.get("once") or []
    listed += data.get("extras") or ["LICENSE.md", "NOTICE"]

    entries = []
    for item in listed:
        if isinstance(item, dict):
            if "from" in item:
                entries.append(str(item["from"]))
        else:
            entries.append(str(item))

    return entries


def tree(owner, repo, ref):
    """
    Every file path in the repository, from the GitHub API.

    Needed because a folder or a wildcard cannot be resolved against
    raw.githubusercontent, which only serves one named file at a time. Returns
    None when the listing is unavailable, so the caller can fall back to
    treating each entry as a literal path.
    """
    url = TREE_URL.format(owner=owner, repo=repo, ref=ref)

    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None

    if data.get("truncated"):
        # Enormous repository. Literal paths still work, patterns would quietly
        # miss files, so it is better to admit to knowing nothing.
        return None

    return [item["path"] for item in data.get("tree", []) if item.get("type") == "blob"]


def fetch(source, ref="master", destination=None):
    """
    Download a library's manifest and the files it lists into a folder.

    The result mirrors the repository's own layout, so manifest.load() and
    install_to() work on it exactly as they do on a local clone.

    Args:
        source: library name, "owner/name", or a GitHub URL.
        ref: branch or tag. These repositories use master.
        destination: where to write. A temporary folder when not given.

    Returns:
        The Path the files were written to. The caller owns it and, when it is
        temporary, is responsible for removing it.
    """
    owner, repo = _split(source)
    root = Path(destination) if destination else Path(tempfile.mkdtemp(prefix="stm32-install-"))
    root.mkdir(parents=True, exist_ok=True)

    raw = _fetch(owner, repo, ref, "library.yml")
    (root / "library.yml").write_bytes(raw)

    try:
        data = yamlreader.parse(raw.decode("utf-8"))
    except (yamlreader.YamlError, UnicodeDecodeError) as error:
        raise DownloadError(f"{owner}/{repo} has a library.yml that cannot be read: {error}")

    if not isinstance(data, dict):
        raise DownloadError(f"{owner}/{repo} has a library.yml that is not a mapping.")

    entries = _listed_entries(data)
    optional = {str(item) for item in (data.get("extras") or ["LICENSE.md", "NOTICE"])}

    # One listing of the repository, and only when something actually needs it.
    known = tree(owner, repo, ref) if any(manifest.is_pattern(e) for e in entries) else None

    wanted = []
    for entry in entries:
        if known is None:
            wanted.append((entry, entry))
            continue

        for path in manifest.expand(None, entry, known):
            wanted.append((path.as_posix(), entry))

    for path, entry in wanted:
        try:
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(_fetch(owner, repo, ref, path))
        except DownloadError:
            if entry in optional:
                # Optional by nature, so a repository missing one is fine.
                continue

            # A plain path that is not a file may be a folder, which only the
            # repository listing can resolve.
            listing = known if known is not None else tree(owner, repo, ref)
            found = manifest.expand(None, entry, listing) if listing else []

            if not found:
                raise

            for extra in found:
                target = root / extra
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(_fetch(owner, repo, ref, extra.as_posix()))

    return root


def _split(source):
    """Owner and repository name from a bare name, an owner/name pair, or a URL."""
    text = str(source).strip().rstrip("/")

    if text.endswith(".git"):
        text = text[: -len(".git")]

    if text.startswith(("http://", "https://")):
        parts = [p for p in text.split("/") if p and p != "https:" and p != "http:"]
        if len(parts) < 3:
            raise DownloadError(f"{source} does not look like a GitHub repository URL.")
        return parts[1], parts[2]

    if "/" in text:
        owner, _, repo = text.partition("/")
        if owner and repo:
            return owner, repo
        raise DownloadError(f"Could not work out the repository from {source!r}.")

    if not text:
        raise DownloadError("No library name given.")

    return DEFAULT_OWNER, text


def cleanup(path):
    """Remove a folder created by fetch(). Never raises."""
    shutil.rmtree(path, ignore_errors=True)
