"""
Tests for fetching a library from GitHub, a private repository included.

Nothing here goes near the network. The opener every request goes through is
replaced by one that answers from a dictionary and remembers what it was asked,
so a test can see where each request went and what it carried with it.
"""

import io
import types
import urllib.error
import urllib.parse
import urllib.request

import pytest

from stm32_installer.core import download

MANIFEST = b"name: demo\nfiles:\n  headers:\n    - demo.h\n  sources:\n    - demo.c\n"


class _Response(io.BytesIO):
    """A response body that also works as a context manager, as urlopen's does."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _ref_of(url):
    """The branch a raw, contents or tree URL asks for."""
    if "?ref=" in url:
        return urllib.parse.unquote(url.split("?ref=")[1])

    if "/git/trees/" in url:
        return url.split("/git/trees/")[1].split("?")[0]

    return url.split("/")[5]


@pytest.fixture
def github(monkeypatch):
    """
    Stand in for GitHub, with no token set.

    Serves each file whose URL ends in a name from files, answers 404 for
    anything else, or answers status for everything when a test sets it. When a
    test sets branches, only those exist, and any other ref is a 404. seen
    collects (url, headers) for every request.
    """
    state = types.SimpleNamespace(
        files={"installer.yml": MANIFEST, "demo.h": b"/* h */\n", "demo.c": b"/* c */\n"},
        seen=[],
        status=None,
        branches=None,
        commits={},
        lookups=[],
    )

    def fake_open(request, timeout=None):
        # Which commit a ref is now, kept apart from the files: answered from
        # commits, and 404 for a ref it does not hold, as GitHub does.
        if "/commits/" in request.full_url:
            state.lookups.append((request.full_url, dict(request.header_items())))
            ref = urllib.parse.unquote(request.full_url.split("/commits/")[1])

            if state.status is None and ref in state.commits:
                return _Response(state.commits[ref].encode("ascii"))

            raise urllib.error.HTTPError(request.full_url, state.status or 404, "Not Found", {}, None)

        state.seen.append((request.full_url, dict(request.header_items())))

        if state.status is not None:
            raise urllib.error.HTTPError(request.full_url, state.status, "Refused", {}, None)

        if state.branches is not None and _ref_of(request.full_url) not in state.branches:
            raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)

        for name, body in state.files.items():
            if request.full_url.split("?")[0].endswith("/" + name):
                return _Response(body)

        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr(download._OPENER, "open", fake_open)

    for name in download.TOKEN_VARIABLES:
        monkeypatch.delenv(name, raising=False)

    return state


def test_without_a_token_nothing_rides_along(github, tmp_path):
    """A public repository, fetched the way it always was: raw files, no credentials."""
    download.fetch("someone/demo", destination=tmp_path / "lib")

    assert github.seen, "nothing was fetched"
    assert all(url.startswith("https://raw.githubusercontent.com/someone/demo/HEAD/") for url, _ in github.seen)
    assert all("Authorization" not in headers for _, headers in github.seen)
    assert (tmp_path / "lib" / "demo.c").read_bytes() == b"/* c */\n"


def test_with_a_token_every_file_comes_from_the_api_with_it(github, monkeypatch, tmp_path):
    """raw.githubusercontent cannot see a private repository. The API can, given the token."""
    monkeypatch.setenv("GITHUB_TOKEN", "t0ken")

    download.fetch("someone/private", destination=tmp_path / "lib")

    assert all(url.startswith("https://api.github.com/repos/someone/private/contents/") for url, _ in github.seen)
    assert all(headers.get("Authorization") == "Bearer t0ken" for _, headers in github.seen)
    assert all(headers.get("Accept") == download.RAW_MEDIA for _, headers in github.seen)
    assert (tmp_path / "lib" / "demo.h").read_bytes() == b"/* h */\n"


def test_gh_token_is_used_when_github_token_is_not_set(github, monkeypatch, tmp_path):
    """The name the gh command reads, so a machine signed in with gh needs nothing more."""
    monkeypatch.setenv("GH_TOKEN", "gh-t0ken")

    download.fetch("someone/private", destination=tmp_path / "lib")

    assert all(headers.get("Authorization") == "Bearer gh-t0ken" for _, headers in github.seen)


def test_github_token_comes_before_gh_token(github, monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_TOKEN", "first")
    monkeypatch.setenv("GH_TOKEN", "second")

    download.fetch("someone/private", destination=tmp_path / "lib")

    assert all(headers.get("Authorization") == "Bearer first" for _, headers in github.seen)


def test_a_private_repository_without_a_token_says_what_to_do(github, tmp_path):
    """GitHub answers 404 for a private repository, so 'does not exist' alone would mislead."""
    del github.files["installer.yml"]

    with pytest.raises(download.DownloadError) as raised:
        download.fetch("someone/private", destination=tmp_path / "lib")

    assert "private" in str(raised.value)
    assert "GITHUB_TOKEN" in str(raised.value)


def test_a_refused_token_is_named_but_never_shown(github, monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_TOKEN", "t0ken-secret")
    github.status = 401

    with pytest.raises(download.DownloadError) as raised:
        download.fetch("someone/private", destination=tmp_path / "lib")

    assert "GITHUB_TOKEN" in str(raised.value)
    assert "t0ken-secret" not in str(raised.value)


def test_a_403_is_not_reported_as_a_missing_file(github, monkeypatch, tmp_path):
    """A token that may not read the repository, or a rate limit, is not 'does not exist'."""
    monkeypatch.setenv("GITHUB_TOKEN", "t0ken")
    github.status = 403

    with pytest.raises(download.DownloadError) as raised:
        download.fetch("someone/private", destination=tmp_path / "lib")

    assert "HTTP 403" in str(raised.value)
    assert "token in GITHUB_TOKEN" in str(raised.value)
    assert "does not exist" not in str(raised.value)


def test_a_redirect_to_another_host_leaves_the_token_behind():
    """
    urllib would carry the Authorization header anywhere a redirect pointed.
    Back to the same host it may go along, which is what a renamed repository does.
    """
    handler = download._SameHostRedirect()
    request = urllib.request.Request("https://api.github.com/repos/a/b/contents/x")
    request.add_header("Authorization", "Bearer t0ken")

    elsewhere = handler.redirect_request(request, None, 302, "Found", {}, "https://example.com/x")
    same = handler.redirect_request(
        request, None, 301, "Moved", {}, "https://api.github.com/repositories/1/contents/x"
    )

    assert not elsewhere.has_header("Authorization")
    assert same.get_header("Authorization") == "Bearer t0ken"


def test_the_repository_listing_carries_the_token(github, monkeypatch):
    """A wildcard in a private repository's manifest needs the listing, and so the token."""
    monkeypatch.setenv("GITHUB_TOKEN", "t0ken")

    download.tree("someone", "private", "master")
    url, headers = github.seen[-1]

    assert url.startswith("https://api.github.com/repos/someone/private/git/trees/master")
    assert headers.get("Authorization") == "Bearer t0ken"


def test_a_branch_with_a_slash_stays_one_ref(github, monkeypatch, tmp_path):
    """feature/x is one ref. Unescaped in the query it would still work, but in a path it would not."""
    monkeypatch.setenv("GITHUB_TOKEN", "t0ken")

    download.fetch("someone/private", ref="feature/x", destination=tmp_path / "lib")
    url, _ = github.seen[0]

    assert url.endswith("/contents/installer.yml?ref=feature%2Fx")


# ----------------------------------------------------------------------------
# With no ref, the default branch, pinned to the commit it is
# ----------------------------------------------------------------------------

SHA = "3f2a9c1" + "0" * 33


def test_no_ref_takes_the_default_branch_whatever_its_name(github, tmp_path):
    """HEAD is git's name for it: main, master or develop, the one GitHub marks default."""
    download.fetch("someone/demo", destination=tmp_path / "lib")

    assert {_ref_of(url) for url, _ in github.seen} == {"HEAD"}
    assert download.origin(tmp_path / "lib") == {
        "kind": "github", "source": "someone/demo", "ref": None, "commit": None, "manifest": None,
    }


def test_every_file_comes_from_the_commit_the_ref_was(github, tmp_path):
    """A push half way through a download cannot mix two versions."""
    github.commits = {"HEAD": SHA}

    download.fetch("someone/demo", destination=tmp_path / "lib")

    assert {_ref_of(url) for url, _ in github.seen} == {SHA}
    assert download.origin(tmp_path / "lib")["commit"] == SHA
    assert github.lookups[0][1].get("Accept") == "application/vnd.github.sha"


def test_a_tag_is_pinned_the_same_way(github, tmp_path):
    github.commits = {"v1.2.0": SHA}

    download.fetch("someone/demo@v1.2.0", destination=tmp_path / "lib")

    assert {_ref_of(url) for url, _ in github.seen} == {SHA}
    assert download.origin(tmp_path / "lib")["ref"] == "v1.2.0"


def test_a_ref_given_is_the_only_one_asked(github, tmp_path):
    github.branches = {"main"}

    with pytest.raises(download.DownloadError):
        download.fetch("someone/demo", ref="master", destination=tmp_path / "lib")

    assert {_ref_of(url) for url, _ in github.seen} == {"master"}


def test_a_refusal_is_reported_as_itself(github, monkeypatch, tmp_path):
    """A refused token is refused for library.yml as well, and must be said as it is."""
    monkeypatch.setenv("GITHUB_TOKEN", "t0ken")
    github.status = 403

    with pytest.raises(download.DownloadError) as raised:
        download.fetch("someone/private", destination=tmp_path / "lib")

    assert len(github.seen) == 1
    assert "HTTP 403" in str(raised.value)


def test_a_missing_manifest_names_the_default_branch(github, tmp_path):
    github.branches = {"develop"}

    with pytest.raises(download.DownloadError) as raised:
        download.fetch("someone/demo", destination=tmp_path / "lib")

    assert "on its default branch" in str(raised.value)
    assert "GITHUB_TOKEN" in str(raised.value)


@pytest.mark.parametrize("source, ref", [
    ("someone/demo@v1.2.0", "v1.2.0"),
    ("someone/demo@feature/x", "feature/x"),
    ("demo@3f2a9c1", "3f2a9c1"),
    ("https://github.com/someone/demo/tree/v1.2.0", "v1.2.0"),
    ("https://github.com/someone/demo", None),
])
def test_a_ref_after_an_at_or_in_a_tree_address_is_the_ref(source, ref):
    assert download._split_ref(source)[2] == ref


def test_two_refs_for_one_library_are_refused(github, tmp_path):
    with pytest.raises(download.DownloadError, match="Give the ref once"):
        download.fetch("someone/demo@v1.0.0", ref="v2.0.0", destination=tmp_path / "lib")


@pytest.mark.parametrize("source", ["someone/demo@", "someone/demo@../x", "someone/demo@-rf"])
def test_a_ref_that_is_no_ref_is_refused(github, source, tmp_path):
    with pytest.raises(download.DownloadError, match="after the @"):
        download.fetch(source, destination=tmp_path / "lib")

    assert github.seen == [] and github.lookups == []


@pytest.mark.parametrize("entry", ["../evil.h", "..\\evil.h", "/etc/passwd", "C:/x.h"])
def test_a_listed_file_outside_the_library_is_never_fetched(github, entry, tmp_path):
    """Each file is written by its own path, so this one would land outside the download."""
    text = "name: demo\nfiles:\n  headers:\n    - demo.h\n  sources:\n    - '%s'\n" % entry
    github.files["installer.yml"] = text.encode("utf-8")

    with pytest.raises(download.DownloadError, match="never fetched"):
        download.fetch("someone/demo", destination=tmp_path / "lib")

    assert [url for url, _ in github.seen if not url.endswith("/installer.yml")] == []


def test_a_carried_manifest_stands_in_for_one_the_repository_lacks(github, tmp_path):
    """littlefs as its authors ship it, with an installer.yml spif carries for it."""
    del github.files["installer.yml"]

    download.fetch("littlefs-project/littlefs", destination=tmp_path / "lib", carried=MANIFEST)

    assert (tmp_path / "lib" / "installer.yml").read_bytes() == MANIFEST
    assert (tmp_path / "lib" / "demo.c").read_bytes() == b"/* c */\n"
    assert download.origin(tmp_path / "lib")["manifest"] == "carried"


def test_an_answer_that_is_no_commit_is_not_used(github, tmp_path):
    """A proxy's error page, say, where a SHA should be: the ref itself is used."""
    github.commits = {"HEAD": "<html>not a commit</html>"}

    download.fetch("someone/demo", destination=tmp_path / "lib")

    assert {_ref_of(url) for url, _ in github.seen} == {"HEAD"}
    assert download.origin(tmp_path / "lib")["commit"] is None
