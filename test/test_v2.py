"""
What 2.0.0 brings to an STM32 project: the key named like the other four
installers', with the old one still read, files of the project's own made once,
and the CMake block on the shared helper, recorded with its fingerprint.
"""

import json

import pytest

from stm32_installer.core import cli, download, manifest, target


@pytest.fixture
def quiet(monkeypatch):
    """Nobody to ask, and no network."""
    monkeypatch.setattr(cli, "_answer", lambda prompt: None)
    monkeypatch.setattr(download, "fetch", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))


def _newer():
    major, minor, _ = (int(part) for part in target.current.version.split("."))

    return f"{major}.{minor + 1}.0"


@pytest.mark.parametrize("key", ["stm32_installer", "installer"])
def test_both_names_of_the_key_are_read(key):
    with pytest.raises(manifest.ManifestError, match="or newer"):
        manifest.check_installer({"requires": {key: _newer()}})


def test_another_installers_key_is_not_this_ones():
    manifest.check_installer({"requires": {"zephyr_installer": _newer()}})


def test_once_files_land_in_the_project(library, project, quiet):
    root = project(cmake=True)
    source = library(once=[{"from": "template/demo_config.h", "to": "VERSION"}],
                     requires={"stm32_installer": "2.0.0"})

    assert cli.main([str(source), "--project", str(root), "--dir", "Libs/demo"]) == 0

    assert (root / "VERSION").read_text() == "#define DEMO_SIZE 8\n"
    assert not (root / "Libs" / "demo" / "VERSION").exists()


@pytest.mark.parametrize("to", ["CMakeLists.txt", "Proj.ioc", "Core/Inc/stm32f4xx_hal_conf.h", "MDK/Proj.uvprojx",
                                "Makefile", ".cproject"])
def test_a_once_file_naming_a_project_file_is_refused(library, project, quiet, to, capsys):
    root = project(cmake=True)
    source = library(once=[{"from": "template/demo_config.h", "to": to}], requires={"installer": "2.0.0"})

    assert cli.main([str(source), "--project", str(root), "--dir", "Libs/demo"]) == 2

    assert "edits or reads as the project's own" in capsys.readouterr().err


def test_the_cmake_block_is_recorded_with_its_fingerprint(library, project, quiet):
    root = project(cmake=True)

    assert cli.main([str(library(once=[])), "--project", str(root), "--dir", "Libs/demo"]) == 0

    record = json.loads((root / ".stm32-installer.json").read_text())["libraries"]["demo"]
    assert list(record["blocks"]["CMakeLists.txt"]) == ["demo"]


def test_a_half_written_block_leaves_the_file_alone(library, project, quiet):
    root = project(cmake=True)
    path = root / "CMakeLists.txt"
    path.write_bytes(path.read_bytes() + b"# <<< stm32-installer: demo <<<\n")
    before = path.read_bytes()

    cli.main([str(library(once=[])), "--project", str(root), "--dir", "Libs/demo"])

    assert path.read_bytes() == before
