"""
Tests for the command line: what it is given decides where the library comes from.

One argument takes a library name, "owner/name", a GitHub URL, a downloaded zip,
or a folder. These tests pin down which is which, what happens to each, and that
nothing here waits for an answer nobody can give.
"""

import io
import os
import zipfile

import pytest

from stm32_installer import cli, download


class _Stream:
    """A stand-in for stdin or stdout, a terminal or not as the test needs."""

    def __init__(self, tty):
        self.tty = tty
        self.text = io.StringIO()

    def isatty(self):
        return self.tty

    def write(self, text):
        return self.text.write(text)

    def flush(self):
        pass


def _zip(folder, archive, top):
    """Zip a library the way GitHub's Download ZIP does: under one top folder."""
    archive.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(archive, "w") as bundle:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                bundle.write(path, f"{top}/{path.relative_to(folder).as_posix()}")

    return archive


def _listing(folder):
    """Every path under a folder, to tell whether anything was changed."""
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*"))


@pytest.fixture
def no_network(monkeypatch):
    """Fail loudly if anything tries to reach GitHub."""

    def refuse(*args, **kwargs):
        raise AssertionError("went online for something that was on disk")

    monkeypatch.setattr(download, "fetch", refuse)


# ----------------------------------------------------------------------------
# A zip, as GitHub's Download ZIP hands it out.
# ----------------------------------------------------------------------------


def test_a_github_zip_installs_without_being_unpacked(library, project, tmp_path, no_network):
    root = project(cmake=True)
    archive = _zip(library(), tmp_path / "Downloads" / "demo-master.zip", "demo-master")
    before = archive.read_bytes()

    code = cli.main([str(archive), "--project", str(root), "--dir", "demo"])

    assert code == 0
    assert (root / "demo" / "demo.h").is_file()
    assert (root / "demo" / "demo.c").is_file()
    assert (root / "demo" / "demo_config.h").is_file()
    assert archive.read_bytes() == before, "the zip was changed"
    assert "add_subdirectory(demo)" in (root / "CMakeLists.txt").read_text(encoding="utf-8")


def test_a_zip_with_no_library_in_it_is_refused(project, tmp_path, no_network, capsys):
    root = project()
    archive = tmp_path / "other.zip"

    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("other-main/readme.txt", "not a library")

    assert cli.main([str(archive), "--project", str(root)]) == 2
    assert "no library.yml" in capsys.readouterr().err


def test_a_file_that_is_not_a_zip_is_refused(project, tmp_path, no_network, capsys):
    root = project()
    notes = tmp_path / "notes.txt"
    notes.write_text("hello\n", encoding="utf-8")

    assert cli.main([str(notes), "--project", str(root)]) == 2
    assert "not a .zip" in capsys.readouterr().err


# ----------------------------------------------------------------------------
# A folder: copied in from outside the project, converted where it stands inside.
# ----------------------------------------------------------------------------


def test_a_folder_outside_the_project_is_copied_and_left_alone(
    library, project, tmp_path, no_network
):
    root = project(cmake=True)
    source = library(root=tmp_path / "Downloads" / "demo-master")
    before = _listing(source)

    code = cli.main([str(source), "--project", str(root), "--dir", "demo"])

    assert code == 0
    assert (root / "demo" / "demo.h").is_file()
    assert _listing(source) == before, "the source folder was changed"


def test_the_folder_windows_extract_all_makes_is_found(library, project, tmp_path, no_network):
    """Extract All puts the zip's own top folder inside another of the same name."""
    root = project(cmake=True)
    outer = tmp_path / "Downloads" / "demo-master"
    library(root=outer / "demo-master")

    code = cli.main([str(outer), "--project", str(root), "--dir", "demo"])

    assert code == 0
    assert (root / "demo" / "demo.h").is_file()


def test_a_folder_inside_the_project_becomes_the_library_where_it_is(
    library, project, no_network
):
    root = project(cmake=True)
    folder = library(root=root / "demo")

    code = cli.main([str(folder), "--project", str(root)])

    assert code == 0
    assert (folder / "demo.h").is_file()
    assert not (folder / "library.yml").exists()
    assert not (folder / "inc").exists()
    assert "add_subdirectory(demo)" in (root / "CMakeLists.txt").read_text(encoding="utf-8")


def test_a_folder_deeper_in_the_project_still_registers_with_the_project(
    library, project, no_network
):
    """
    The project is where the command runs, not the folder above the library.

    Taking the parent broke Libs/demo: Libs was taken for the project, no IDE
    was found there, and the library was never registered.
    """
    root = project(cmake=True)
    folder = library(root=root / "Libs" / "demo")

    code = cli.main([str(folder), "--project", str(root)])

    assert code == 0
    assert "add_subdirectory(Libs/demo)" in (root / "CMakeLists.txt").read_text(encoding="utf-8")
    assert (root / ".stm32-installer.json").is_file()


def test_dir_is_refused_for_a_folder_already_in_the_project(library, project, no_network):
    """It becomes the library where it stands, so there is nowhere to send it."""
    root = project(cmake=True)
    folder = library(root=root / "demo-master")

    assert cli.main([str(folder), "--project", str(root), "--dir", "demo"]) == 2
    assert (folder / "library.yml").is_file(), "the folder was converted anyway"


def test_run_from_inside_the_library_folder_its_parent_is_the_project(
    library, project, monkeypatch, no_network
):
    root = project(cmake=True)
    folder = library(root=root / "demo")
    monkeypatch.chdir(folder)

    assert cli.main(["."]) == 0
    assert "add_subdirectory(demo)" in (root / "CMakeLists.txt").read_text(encoding="utf-8")


def test_an_install_py_from_an_older_release_still_works(library, project, monkeypatch, no_network):
    """Those pass the folder they sit in, and are run from the project root."""
    root = project(cmake=True)
    folder = library(root=root / "demo")
    monkeypatch.chdir(root)

    assert cli.main(argv=[], library_root=folder) == 0
    assert (folder / "demo.h").is_file()
    assert not (folder / "library.yml").exists()


# ----------------------------------------------------------------------------
# Names and paths: which one an argument is.
# ----------------------------------------------------------------------------


def test_a_name_goes_to_github(library, project, tmp_path, monkeypatch):
    root = project(cmake=True)
    staged = library(root=tmp_path / "staged")
    calls = []

    def fake_fetch(source, ref="master", destination=None):
        calls.append((source, ref))
        return staged

    monkeypatch.setattr(download, "fetch", fake_fetch)

    code = cli.main(["nimaltd/demo", "--project", str(root), "--dir", "demo", "--ref", "2.0.0"])

    assert code == 0
    assert calls == [("nimaltd/demo", "2.0.0")]
    assert (root / "demo" / "demo.h").is_file()


def test_an_existing_folder_wins_over_a_library_name(library, project, monkeypatch, no_network):
    root = project(cmake=True)
    library(root=root / "demo")
    monkeypatch.chdir(root)

    assert cli.main(["demo"]) == 0
    assert (root / "demo" / "demo.h").is_file()


@pytest.mark.parametrize(
    "target",
    [
        "D:/Downloads/no-such-library-9f3.zip",
        "./no-such-library-9f3",
        "Libs/no-such/library-9f3",
        "C:\\no-such-folder-9f3\\demo",
    ],
)
def test_a_path_that_does_not_exist_is_not_sent_to_github(target, project, no_network, capsys):
    """Sent there, a mistyped path comes back as a repository nobody has heard of."""
    root = project()

    assert cli.main([target, "--project", str(root)]) == 2
    assert "does not exist" in capsys.readouterr().err


# ----------------------------------------------------------------------------
# What it says at the end.
# ----------------------------------------------------------------------------


def test_the_last_line_names_the_real_header(library, project, tmp_path, no_network, capsys):
    """The sequencer library is called sequencer, and its header is seq.h."""
    root = project(cmake=True)
    source = library(
        root=tmp_path / "Downloads" / "sequencer-master",
        name="sequencer",
        headers=("src/seq.h",),
        sources=("src/seq.c",),
        once=[],
    )

    code = cli.main([str(source), "--project", str(root), "--dir", "sequencer"])
    out = capsys.readouterr().out

    assert code == 0
    assert '#include "seq.h"' in out
    assert "sequencer.h" not in out


def test_the_last_line_is_relative_to_the_include_folder(
    library, project, tmp_path, no_network, capsys
):
    """With a mirror layout the header lands in inc/, which is on the include path."""
    root = project(cmake=True)
    source = library(root=tmp_path / "Downloads" / "demo-master", install={"layout": "mirror"})

    assert cli.main([str(source), "--project", str(root), "--dir", "demo"]) == 0
    assert '#include "demo.h"' in capsys.readouterr().out


# ----------------------------------------------------------------------------
# The folder question, which must never hang and never mean yes to Ctrl+C.
# ----------------------------------------------------------------------------


def test_nobody_is_asked_when_nobody_can_answer(monkeypatch):
    """A script or a build server would otherwise wait for an answer for ever."""

    def refuse(*args, **kwargs):
        raise AssertionError("opened the console with nobody at it")

    monkeypatch.setattr(cli.sys, "stdin", _Stream(tty=False))
    monkeypatch.setattr(cli.sys, "stdout", _Stream(tty=False))
    monkeypatch.setattr(cli, "open", refuse, raising=False)

    assert cli._ask_folder("demo") == "demo"


def test_a_piped_run_reads_the_answer_from_the_console(monkeypatch):
    """Piped into Python, stdin is the script, so the answer comes from the console."""
    devices = []

    def console(device, mode="r"):
        devices.append(device)
        return io.StringIO("Libs/demo\n")

    monkeypatch.setattr(cli.sys, "stdin", _Stream(tty=False))
    monkeypatch.setattr(cli.sys, "stdout", _Stream(tty=True))
    monkeypatch.setattr(cli, "open", console, raising=False)

    assert cli._ask_folder("demo") == "Libs/demo"
    assert devices == ["CONIN$" if os.name == "nt" else "/dev/tty"]


def test_the_folder_defaults_to_the_library_name(library, project, tmp_path, monkeypatch, no_network):
    """Not the name of the zip or folder it came from, which carries -master."""
    root = project(cmake=True)
    source = library(root=tmp_path / "Downloads" / "demo-master")

    def refuse(*args, **kwargs):
        # Without this, a regression that asks with nobody at the screen would
        # not fail this test, it would hang it, and with it the whole CI run.
        raise AssertionError("opened the console with nobody at it")

    monkeypatch.setattr(cli.sys, "stdin", _Stream(tty=False))
    monkeypatch.setattr(cli.sys, "stdout", _Stream(tty=False))
    monkeypatch.setattr(cli, "open", refuse, raising=False)

    assert cli.main([str(source), "--project", str(root)]) == 0
    assert (root / "demo" / "demo.h").is_file()


def test_ctrl_c_at_the_question_stops_the_install(library, project, tmp_path, monkeypatch, no_network):
    """It used to be taken as "use the default", and the install went ahead."""
    root = project(cmake=True)
    source = library(root=tmp_path / "Downloads" / "demo-master")

    def interrupted(prompt=""):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli.sys, "stdin", _Stream(tty=True))
    monkeypatch.setattr(cli, "input", interrupted, raising=False)

    assert cli.main([str(source), "--project", str(root)]) == 130
    assert not (root / "demo").exists()
