"""
Tests for the built in YAML reader.

The important ones compare it against PyYAML on the same text. Two readers that
disagree would mean a manifest behaving differently depending on what happens to
be installed on the user's machine, which is the sort of bug nobody can
reproduce.
"""

import pytest

from stm32_installer import yamlreader

pyyaml = pytest.importorskip("yaml", reason="PyYAML is needed to compare the two readers")


REAL_MANIFEST = """\
# Read by stm32-installer.

name: fsm
version: 2.0.0
description: Finite state machine and task queue for STM32
repository: https://github.com/nimaltd/fsm
license: Apache-2.0

kind: middleware
category: system

provides: []

requires:
  libraries: []
  hal: true           # needs HAL_GetTick
  cmsis: true
  rtos: none
  hal_modules: []
  peripherals: []
  c_standard: c11

files:
  headers:
    - inc/fsm.h
  sources:
    - src/fsm.c

once:
  - from: src/seq_config.h
"""

COMPLICATED = """\
name: spif
version: 3.0.0
kind: driver
requires:
  hal_modules: [spi, gpio, dma]
  rtos: optional
  peripherals:
    - type: spi
      count: 1
      note: Master mode, 8 bit
    - type: gpio
      count: 2
      note: Chip select and write protect
files:
  headers:
    - inc/spif.h
    - inc/spif_port.h
  sources:
    - src/spif.c
once:
  - from: src/spif_config.h
  - from: src/spif_port.c
    to: my_port.c
extras: [LICENSE.md, NOTICE]
"""

SCALARS = """\
a_string: hello
a_quoted: 'has: a colon'
a_double: "trailing space "
a_number: 42
a_float: 1.5
a_version: 2.0.0
a_true: true
a_yes: yes
a_false: false
a_no: no
a_null: null
a_tilde: ~
an_empty:
a_hash_in_value: red#blue
a_url: https://github.com/nimaltd/fsm
"""


@pytest.mark.parametrize(
    "text",
    [REAL_MANIFEST, COMPLICATED, SCALARS],
    ids=["real-manifest", "complicated", "scalars"],
)
def test_matches_pyyaml(text):
    assert yamlreader.loads(text) == pyyaml.safe_load(text)


def test_matches_pyyaml_on_every_manifest_in_the_repositories(tmp_path):
    """Whatever he actually writes is the text that has to work."""
    from pathlib import Path

    repos = Path(__file__).resolve().parent.parent.parent
    manifests = list(repos.glob("*/library.yml"))

    if not manifests:
        pytest.skip("no sibling library repositories checked out")

    for path in manifests:
        text = path.read_text(encoding="utf-8")
        assert yamlreader.loads(text) == pyyaml.safe_load(text), f"{path} parses differently"


def test_a_comment_inside_quotes_is_kept():
    assert yamlreader.loads("note: 'a # b'") == {"note": "a # b"}


def test_a_trailing_comment_is_dropped():
    assert yamlreader.loads("name: fsm   # the library") == {"name": "fsm"}


def test_an_empty_document_is_none():
    assert yamlreader.loads("# only a comment\n\n") is None


def test_tabs_are_refused_rather_than_guessed():
    with pytest.raises(yamlreader.YamlError, match="tab"):
        yamlreader.loads("files:\n\theaders: []\n")


def test_unsupported_nesting_is_refused_not_guessed():
    with pytest.raises(yamlreader.YamlError):
        yamlreader.loads("a: [[1, 2], [3]]\n")


def test_parse_uses_pyyaml_when_it_is_installed(monkeypatch):
    seen = {}

    def fake_safe_load(text):
        seen["called"] = True
        return {"ok": True}

    monkeypatch.setattr(pyyaml, "safe_load", fake_safe_load)

    assert yamlreader.parse("name: fsm") == {"ok": True}
    assert seen["called"]


def test_parse_falls_back_when_pyyaml_is_missing(monkeypatch):
    """This is the path a machine with nothing but Python takes."""
    import builtins

    real_import = builtins.__import__

    def no_yaml(name, *args, **kwargs):
        if name == "yaml":
            raise ImportError("no yaml here")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_yaml)

    assert yamlreader.parse(REAL_MANIFEST)["name"] == "fsm"
