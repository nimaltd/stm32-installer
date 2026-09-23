"""
Two versions a library.yml deals with, and where each one lives.

The library's own version is not written in library.yml any more. It is read
from the @version tag in the file comment of the library's first header, so it
lives in one place, the code, and cannot drift from what it describes.

The installer's version is: requires.installer names the oldest stm32-installer
that reads the file correctly, and an older one stops before it reads anything
else, rather than misreading something it does not understand.
"""

import zipfile

import pytest

import stm32_installer
from stm32_installer import cli, console, download, manifest

HEADER = "/**\n * @file        demo.h\n * @version     {version}\n */\n\n#ifndef DEMO_H\n"


def _newer():
    """A version one minor release past this installer."""
    major, minor, _ = (int(part) for part in stm32_installer.__version__.split("."))

    return f"{major}.{minor + 1}.0"


# ----------------------------------------------------------------------------
# The library's version, read from the code.
# ----------------------------------------------------------------------------


def test_the_version_comes_from_the_header(library):
    root = library(version=None, extra_files={"inc/demo.h": HEADER.format(version="2.3.4")})

    assert manifest.load(root).version == "2.3.4"


def test_the_header_wins_over_a_version_left_in_library_yml(library):
    """The code is what gets compiled, so the code is what the number describes."""
    root = library(version="1.0.0", extra_files={"inc/demo.h": HEADER.format(version="2.3.4")})

    assert manifest.load(root).version == "2.3.4"


def test_library_yml_is_still_read_for_a_header_without_a_version(library):
    root = library(version="1.0.0")

    assert manifest.load(root).version == "1.0.0"


def test_no_version_anywhere_shows_none(library):
    root = library(version=None)

    assert manifest.load(root).version == ""


def test_the_banner_leaves_out_a_missing_version():
    """Output is plain in tests, since it is not going to a terminal."""
    assert console.banner("demo", "").splitlines()[0] == "demo"
    assert console.banner("demo", "2.0.0").splitlines()[0] == "demo 2.0.0"


def test_the_record_keeps_the_version_from_the_header(library, project, tmp_path):
    root = project(cmake=True)
    source = library(
        root=tmp_path / "Downloads" / "demo-master",
        version=None,
        extra_files={"inc/demo.h": HEADER.format(version="2.3.4")},
    )

    assert cli.main([str(source), "--project", str(root), "--dir", "demo"]) == 0
    assert '"version": "2.3.4"' in (root / ".stm32-installer.json").read_text(encoding="utf-8")


# ----------------------------------------------------------------------------
# The installer's version, required by the library.
# ----------------------------------------------------------------------------


def test_a_library_for_a_newer_installer_is_refused(library):
    root = library(requires={"installer": _newer()})

    with pytest.raises(manifest.ManifestError) as raised:
        manifest.load(root)

    assert f"needs stm32-installer {_newer()} or newer" in str(raised.value)
    assert "pip install --upgrade" in str(raised.value)


def test_a_library_for_this_installer_loads(library):
    root = library(requires={"installer": stm32_installer.__version__})

    assert manifest.load(root).name == "demo"


def test_a_two_part_installer_version_is_refused(library):
    """Unquoted, YAML reads 1.10 as the number 1.1, and the minor part is lost."""
    root = library(requires={"installer": 1.1})

    with pytest.raises(manifest.ManifestError) as raised:
        manifest.load(root)

    assert "three numbers" in str(raised.value)


def test_the_check_comes_before_anything_else_is_read(library):
    """A manifest for a newer installer may not have the fields this one expects."""
    root = library(requires={"installer": _newer()})
    text = (root / "library.yml").read_text(encoding="utf-8").replace("files:", "sources_v9:")
    (root / "library.yml").write_text(text, encoding="utf-8")

    with pytest.raises(manifest.ManifestError) as raised:
        manifest.load(root)

    assert "needs stm32-installer" in str(raised.value)


def test_online_it_stops_before_downloading_a_single_listed_file(monkeypatch, tmp_path):
    requested = []
    staging = tmp_path / "staging"

    def fake_fetch(owner, repo, ref, path):
        requested.append(path)

        if path == "library.yml":
            return (
                "name: demo\n"
                f"requires:\n  installer: {_newer()}\n"
                "files:\n  headers: [inc/demo.h]\n  sources: [src/demo.c]\n"
            ).encode("utf-8")

        raise AssertionError(f"downloaded {path} for an installer too old to read it")

    monkeypatch.setattr(download, "_fetch", fake_fetch)
    monkeypatch.setattr(download.tempfile, "mkdtemp", lambda prefix="": str(staging))

    with pytest.raises(download.DownloadError) as raised:
        download.fetch("nimaltd/demo")

    assert "needs stm32-installer" in str(raised.value)
    assert requested == ["library.yml"]
    assert not staging.exists(), "the temporary folder was left behind"


def test_from_a_zip_nothing_reaches_the_project(library, project, tmp_path, capsys):
    root = project(cmake=True)
    source = library(requires={"installer": _newer()})
    archive = tmp_path / "Downloads" / "demo-master.zip"
    archive.parent.mkdir(parents=True)

    with zipfile.ZipFile(archive, "w") as bundle:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                bundle.write(path, f"demo-master/{path.relative_to(source).as_posix()}")

    before = (root / "CMakeLists.txt").read_text(encoding="utf-8")

    assert cli.main([str(archive), "--project", str(root), "--dir", "demo"]) == 2
    assert "needs stm32-installer" in capsys.readouterr().err
    assert not (root / "demo").exists()
    assert (root / "CMakeLists.txt").read_text(encoding="utf-8") == before
