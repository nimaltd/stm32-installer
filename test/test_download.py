"""
Tests for fetching a library from GitHub, a private repository included.

Nothing here goes near the network. The opener every request goes through is
replaced by one that answers from a dictionary and remembers what it was asked,
so a test can see where each request went and what it carried with it.
"""

import io
import types
import urllib.error
import urllib.request

import pytest

from stm32_installer import download

MANIFEST = b"name: demo\nfiles:\n  headers:\n    - demo.h\n  sources:\n    - demo.c\n"


class _Response(io.BytesIO):
    """A response body that also works as a context manager, as urlopen's does."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


@pytest.fixture
def github(monkeypatch):
    """
    Stand in for GitHub, with no token set.

    Serves each file whose URL ends in a name from files, answers 404 for
    anything else, or answers status for everything when a test sets it. seen
    collects (url, headers) for every request.
    """
    state = types.SimpleNamespace(
        files={"library.yml": MANIFEST, "demo.h": b"/* h */\n", "demo.c": b"/* c */\n"},
        seen=[],
        status=None,
    )

    def fake_open(request, timeout=None):
        state.seen.append((request.full_url, dict(request.header_items())))

        if state.status is not None:
            raise urllib.error.HTTPError(request.full_url, state.status, "Refused", {}, None)

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
    assert all(url.startswith("https://raw.githubusercontent.com/someone/demo/master/") for url, _ in github.seen)
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
    del github.files["library.yml"]

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

    assert url.endswith("/contents/library.yml?ref=feature%2Fx")
