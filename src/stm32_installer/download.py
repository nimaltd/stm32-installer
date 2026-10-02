"""
Getting a library ready to install: fetched from GitHub, or unpacked from
the zip GitHub offers for download.

Only the files the manifest actually lists are downloaded. GitHub can only hand
out a zip of an entire repository, so the zip is avoided: the manifest is read
first, then each listed file is fetched on its own. For a library whose repo
carries a vendored test framework, that is the difference between a few hundred
kilobytes and a few.

A private repository needs a GitHub token that can read it, in GITHUB_TOKEN or
GH_TOKEN. With one, every file comes from the API rather than from
raw.githubusercontent, which cannot see a private repository at all.
"""

import json
import os
import shutil
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from . import manifest, yamlreader

RAW_URL = "https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}"
CONTENTS_URL = "https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={ref}"
TREE_URL = "https://api.github.com/repos/{owner}/{repo}/git/trees/{ref}?recursive=1"
DEFAULT_OWNER = "nimaltd"

# Tried in this order when no ref is given. GitHub names the first branch of a
# new repository main, and older repositories are on master.
DEFAULT_BRANCHES = ("main", "master")
TIMEOUT_SECONDS = 30

# Where a token is looked for, in this order. GitHub Actions sets the first and
# the gh command reads the second, so a machine set up for either works as it
# is. Never an option on the command line, where it would stay in the shell's
# history.
TOKEN_VARIABLES = ("GITHUB_TOKEN", "GH_TOKEN")

# The file as it is, not wrapped in JSON and base64 the way the API hands a file
# out by default.
RAW_MEDIA = "application/vnd.github.raw"


class DownloadError(Exception):
    """A library could not be fetched, with a reason worth showing the user."""


class NotFoundError(DownloadError):
    """GitHub answered 404: no such file, branch or repository, or a private one."""


class _SameHostRedirect(urllib.request.HTTPRedirectHandler):
    """
    Follow a redirect, but take the token only as far as the host it was for.

    urllib copies every header over to wherever a redirect points, the
    Authorization header included, and GitHub does redirect, for a renamed
    repository to start with. A token must not travel anywhere but back to the
    host it was sent to.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)

        if new is not None:
            before = urllib.parse.urlsplit(req.full_url).hostname
            after = urllib.parse.urlsplit(newurl).hostname

            if before != after:
                new.remove_header("Authorization")

        return new


_OPENER = urllib.request.build_opener(_SameHostRedirect)


def _token():
    """(variable, token) for the first token set in the environment, or (None, None)."""
    for name in TOKEN_VARIABLES:
        value = os.environ.get(name, "").strip()

        if value:
            return name, value

    return None, None


def _open(url, token=None, accept=None):
    """Open a URL, sending the token when there is one."""
    request = urllib.request.Request(url)

    if token:
        request.add_header("Authorization", f"Bearer {token}")

    if accept:
        request.add_header("Accept", accept)

    return _OPENER.open(request, timeout=TIMEOUT_SECONDS)


def _fetch(owner, repo, ref, path):
    """Fetch one file's bytes. Raises DownloadError with a readable message."""
    variable, token = _token()

    if token:
        url = CONTENTS_URL.format(
            owner=owner, repo=repo, path=urllib.parse.quote(path), ref=urllib.parse.quote(ref, safe="")
        )
    else:
        url = RAW_URL.format(owner=owner, repo=repo, ref=ref, path=path)

    try:
        with _open(url, token, RAW_MEDIA if token else None) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        if error.code == 401 and token:
            raise DownloadError(
                f"GitHub did not accept the token in {variable}. It may have expired, or been revoked."
            ) from error

        if error.code == 403:
            raise DownloadError(
                f"GitHub refused access to {owner}/{repo} (HTTP 403)"
                + (
                    f" with the token in {variable}. It may not be allowed to read this repository."
                    if token else
                    ". That is usually its limit on requests without a token: wait, or set GITHUB_TOKEN."
                )
            ) from error

        if error.code == 404:
            # GitHub answers a private repository it will not show you with 404,
            # the same as one that does not exist. Only the manifest is asked for
            # first, so that is where a missing token shows up.
            hint = _private_hint(variable, token) if path == "library.yml" else ""

            raise NotFoundError(f"{path} does not exist in {owner}/{repo} at {ref}.{hint}") from error

        raise DownloadError(f"Could not download {path} from {owner}/{repo}: HTTP {error.code}.") from error
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


def _private_hint(variable, token):
    """What to say when a manifest is not found, in case the repository is private."""
    if token:
        return f" If the repository is private, the token in {variable} cannot read it."

    return " If the repository is private, set GITHUB_TOKEN to a token that can read it."


def _manifest(owner, repo, ref):
    """
    The bytes of library.yml, and the ref they came from.

    With no ref, main is tried first and then master, so a repository on either
    branch installs without --ref. Only a 404 moves on to the next branch. Any
    other failure, a refused token or no network, would fail the same way on
    master, and would then be reported as the wrong problem.
    """
    if ref is not None:
        return _fetch(owner, repo, ref, "library.yml"), ref

    for branch in DEFAULT_BRANCHES:
        try:
            return _fetch(owner, repo, branch, "library.yml"), branch
        except NotFoundError:
            continue

    raise NotFoundError(
        f"library.yml does not exist in {owner}/{repo} on "
        f"{' or '.join(DEFAULT_BRANCHES)}.{_private_hint(*_token())}"
    )


def tree(owner, repo, ref):
    """
    Every file path in the repository, from the GitHub API.

    Needed because a folder or a wildcard cannot be resolved against
    raw.githubusercontent, which only serves one named file at a time. Returns
    None when the listing is unavailable, so the caller can fall back to
    treating each entry as a literal path.
    """
    url = TREE_URL.format(owner=owner, repo=repo, ref=urllib.parse.quote(ref, safe=""))

    try:
        with _open(url, _token()[1], "application/vnd.github+json") as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None

    if data.get("truncated"):
        # Enormous repository. Literal paths still work, patterns would quietly
        # miss files, so it is better to admit to knowing nothing.
        return None

    return [item["path"] for item in data.get("tree", []) if item.get("type") == "blob"]


def fetch(source, ref=None, destination=None):
    """
    Download a library's manifest and the files it lists into a folder.

    The result mirrors the repository's own layout, so manifest.load() and
    install_to() work on it exactly as they do on a local clone.

    Args:
        source: library name, "owner/name", or a GitHub URL.
        ref: branch, tag or commit. None tries main, then master.
        destination: where to write. A temporary folder when not given.

    Returns:
        The Path the files were written to. The caller owns it and, when it is
        temporary, is responsible for removing it.
    """
    owner, repo = _split(source)
    temporary = destination is None
    root = Path(destination) if destination else Path(tempfile.mkdtemp(prefix="stm32-install-"))
    root.mkdir(parents=True, exist_ok=True)

    try:
        _fill(owner, repo, ref, root)
    except DownloadError:
        # Half a library is of no use, and nobody else knows this folder
        # exists, since it was never returned. A folder the caller passed in
        # is theirs, and is left alone.
        if temporary:
            cleanup(root)
        raise

    return root


def _fill(owner, repo, ref, root):
    """Download the manifest, then every file it lists, into root."""
    # Every file then comes from the branch the manifest was found on.
    raw, ref = _manifest(owner, repo, ref)
    (root / "library.yml").write_bytes(raw)

    try:
        data = yamlreader.parse(raw.decode("utf-8"))
    except (yamlreader.YamlError, UnicodeDecodeError) as error:
        raise DownloadError(f"{owner}/{repo} has a library.yml that cannot be read: {error}")

    if not isinstance(data, dict):
        raise DownloadError(f"{owner}/{repo} has a library.yml that is not a mapping.")

    # Before a single listed file is fetched. A manifest for a newer installer
    # may list its files in a way this one would get wrong.
    try:
        manifest.check_installer(data)
    except manifest.ManifestError as error:
        raise DownloadError(str(error)) from error

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


def find_root(folder):
    """
    The folder holding library.yml: the one given, or the only one inside it.

    GitHub's zip holds a single top folder, example-main, and Windows' Extract
    All puts that inside another folder of the same name. Either is what a user
    will point at, so both have to work. None when neither holds a manifest, or
    when several subfolders do and picking one would be a guess.
    """
    folder = Path(folder)

    if (folder / "library.yml").is_file():
        return folder

    try:
        found = [
            child
            for child in sorted(folder.iterdir())
            if child.is_dir() and (child / "library.yml").is_file()
        ]
    except OSError:
        return None

    return found[0] if len(found) == 1 else None


def unpack(archive):
    """
    Unpack a library zip into a temporary folder.

    Returns (staging, root): the folder to hand to cleanup() when done, and the
    library inside it. Raises DownloadError when the file is not a zip or holds
    no library, and leaves nothing behind either way.
    """
    staging = Path(tempfile.mkdtemp(prefix="stm32-install-"))

    try:
        with zipfile.ZipFile(archive) as bundle:
            # extractall will not write outside the folder it is given: it
            # drops absolute paths and ".." from the names inside the zip.
            bundle.extractall(staging)
    except (zipfile.BadZipFile, OSError) as error:
        cleanup(staging)
        raise DownloadError(f"{Path(archive).name} is not a usable zip: {error}")

    root = find_root(staging)

    if root is None:
        cleanup(staging)
        raise DownloadError(
            f"{Path(archive).name} holds no library.yml, so there is no library in it to install."
        )

    return staging, root


def cleanup(path):
    """Remove a folder created by fetch() or unpack(). Never raises."""
    shutil.rmtree(path, ignore_errors=True)
