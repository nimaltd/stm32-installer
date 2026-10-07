"""
Tests for a connection to GitHub that is bad, as in Iran.

From a user's machine, installing spif with littlefs: GitHub closed the
connection while osal and littlefs were fetched, and the run ended in a Python
traceback. urllib leaves a dropped connection or a read cut short as it is,
not wrapped in a URLError, so nothing caught it. Now each file is tried five
times, taking turns between raw.githubusercontent.com and api.github.com, and
what still fails is said in words, with what to do about it.
"""

import http.client
import io
import urllib.error

import pytest

from stm32_installer import cli, download

MANIFEST = b"name: demo\nfiles:\n  headers:\n    - demo.h\n  sources:\n    - demo.c\n"
FILES = {"installer.yml": MANIFEST, "demo.h": b"/* h */\n", "demo.c": b"/* c */\n"}


class _Response(io.BytesIO):
    """A response whose read can be made to break part way."""

    def __init__(self, body, cut=False):
        super().__init__(body)
        self.cut = cut

    def read(self, *args):
        if self.cut:
            raise http.client.IncompleteRead(b"/* h", 4)

        return super().read(*args)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


@pytest.fixture
def flaky(monkeypatch):
    """
    GitHub over a bad link. faults lists what each request meets in turn: an
    exception, "cut" for a read cut short, or None for a good answer. Once it
    runs out, every request is answered well. requests records (host, file,
    Accept) for each, and sleeps each wait.
    """
    state = {"faults": [], "requests": [], "sleeps": []}

    def fake_open(request, timeout=None):
        url = request.full_url.split("?")[0]
        host = url.split("/")[2]
        state["requests"].append((host, url.rsplit("/", 1)[1], request.get_header("Accept")))
        fault = state["faults"].pop(0) if state["faults"] else None

        if isinstance(fault, Exception):
            raise fault

        for name, body in FILES.items():
            if url.endswith("/" + name):
                return _Response(body, cut=(fault == "cut"))

        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr(download._OPENER, "open", fake_open)
    monkeypatch.setattr(download.time, "sleep", lambda seconds: state["sleeps"].append(seconds))
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)

    return state


def _dropped():
    return http.client.RemoteDisconnected("Remote end closed connection without response")


def _http(code):
    return urllib.error.HTTPError("u", code, "Refused", {}, None)


def test_a_dropped_connection_is_tried_again_on_the_other_host(flaky, tmp_path):
    """The traceback from the user's machine."""
    flaky["faults"] = [_dropped()]

    download.fetch("someone/demo", destination=tmp_path / "lib")

    assert (tmp_path / "lib" / "demo.c").read_bytes() == b"/* c */\n"
    assert flaky["requests"][:2] == [
        ("raw.githubusercontent.com", "installer.yml", None),
        ("api.github.com", "installer.yml", download.RAW_MEDIA),
    ]
    assert flaky["sleeps"] == [1]


@pytest.mark.parametrize("fault", [
    ConnectionResetError(10054, "An existing connection was forcibly closed by the remote host"),
    TimeoutError("The read operation timed out"),
    urllib.error.URLError("getaddrinfo failed"),
    "cut",
    _http(503),
])
def test_what_a_bad_link_does_is_tried_again(fault, flaky, tmp_path):
    flaky["faults"] = [fault]

    download.fetch("someone/demo", destination=tmp_path / "lib")

    assert (tmp_path / "lib" / "installer.yml").read_bytes() == MANIFEST


def test_the_api_limit_without_a_token_lets_the_other_host_answer(flaky, tmp_path):
    flaky["faults"] = [_dropped(), _http(403)]

    download.fetch("someone/demo", destination=tmp_path / "lib")

    assert [host for host, _, _ in flaky["requests"][:3]] == [
        "raw.githubusercontent.com", "api.github.com", "raw.githubusercontent.com",
    ]


def test_a_refusal_to_a_token_is_not_tried_again(flaky, monkeypatch, tmp_path):
    """The same answer every time, so it is reported at once, from the API only."""
    monkeypatch.setenv("GITHUB_TOKEN", "t0ken")
    flaky["faults"] = [_http(403)]

    with pytest.raises(download.DownloadError, match="HTTP 403"):
        download.fetch("someone/private", destination=tmp_path / "lib")

    assert flaky["requests"] == [("api.github.com", "installer.yml", download.RAW_MEDIA)]
    assert flaky["sleeps"] == []


def test_a_link_that_keeps_breaking_is_reported_with_what_to_do(flaky, tmp_path):
    flaky["faults"] = [_dropped()] * download.ATTEMPTS

    with pytest.raises(download.DownloadError) as raised:
        download.fetch("someone/demo", destination=tmp_path / "lib")

    message = str(raised.value)
    assert "Could not fetch installer.yml from someone/demo, after 5 tries" in message
    assert "Remote end closed connection" in message
    assert "HTTPS_PROXY" in message
    assert "Download ZIP" in message
    assert flaky["sleeps"] == [1, 2, 4, 8]


def test_a_404_is_not_tried_again(flaky, tmp_path):
    """GitHub's answer, the same every time, and the manifest's fallback runs on it."""
    del FILES["installer.yml"]

    try:
        with pytest.raises(download.DownloadError):
            download.fetch("someone/demo", destination=tmp_path / "lib")
    finally:
        FILES["installer.yml"] = MANIFEST

    assert flaky["sleeps"] == []
    assert [name for _, name, _ in flaky["requests"]] == ["installer.yml", "library.yml"] * 2


def test_the_command_line_says_it_rather_than_a_traceback(flaky, library, project, capsys):
    root = project(cmake=True)
    source = library(requires={"libraries": ["osal"]})
    flaky["faults"] = [_dropped()] * download.ATTEMPTS

    assert cli.main([str(source), "--project", str(root), "--dir", "demo"]) == 2

    err = capsys.readouterr().err
    assert "Could not fetch installer.yml from nimaltd/osal" in err
    assert "Traceback" not in err
    assert not (root / "demo").exists(), "installed with a library it needs missing"


def test_a_listing_cut_short_counts_as_no_listing(monkeypatch):
    """Patterns then fall back to plain paths, as with no listing at all."""
    monkeypatch.setattr(download, "_open", lambda *args, **kwargs: _Response(b"{}", cut=True))

    assert download.tree("someone", "demo", "main") is None
