"""
Taking a library out of an STM32 project, and out of every IDE that builds it.

The strongest check there is: install into a project with every IDE file
CubeMX can write, uninstall, and each of those files is back to the byte it
was, whatever the library brought with it. The one exception is spaces at the
end of a line of the Makefile: CubeMX leaves two after the last file of a list,
the install tidies them away as it adds a backslash there, and make never saw
them.
"""

import re

import pytest

from stm32_installer.core import cli, download

PROJECT_FILES = (
    "CMakeLists.txt",
    ".cproject",
    "MDK/Proj.uvprojx",
    "EWARM/Proj.ewp",
    "EWARM/Proj.ewt",
    "Makefile",
)


@pytest.fixture
def no_network(monkeypatch):
    """Fail loudly if a test that should stay offline goes online."""

    def refuse(*args, **kwargs):
        raise AssertionError("tried to use the network")

    monkeypatch.setattr(download, "fetch", refuse)


@pytest.fixture
def nobody(monkeypatch):
    """Nobody at the keyboard: every question takes its default."""
    monkeypatch.setattr(cli, "_answer", lambda prompt: None)


def _every_ide(project, newline="\n"):
    return project(cmake=True, cubeide=True, keil=True, iar=True, makefile=True, newline=newline)


def _snapshot(root):
    found = {name: (root / name).read_bytes() for name in PROJECT_FILES}
    found["Makefile"] = re.sub(rb"[ \t]+(\r?\n)", rb"\1", found["Makefile"])

    return found


def _install(*args):
    assert cli.main([str(arg) for arg in args]) == 0


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
@pytest.mark.parametrize("layout", ["flat", "mirror"])
def test_every_project_file_is_back_as_it_was(library, project, nobody, no_network, newline, layout, capsys):
    root = _every_ide(project, newline)
    before = _snapshot(root)
    lib = library(once=[], sources=("src/demo.c", "src/demo_port.c"),
                  install={"layout": layout, "defines": ["DEMO_FAST", "DEMO_SIZE=8"]})

    _install(lib, "--project", root, "--dir", "Libs/demo")
    assert _snapshot(root) != before

    assert cli.main(["--uninstall", "demo", "--project", str(root)]) == 0

    after = _snapshot(root)
    for name in PROJECT_FILES:
        assert after[name] == before[name], name

    assert not (root / "Libs" / "demo").exists()

    out = capsys.readouterr().out
    for ide in ("CMake", "STM32CubeIDE", "Keil MDK", "IAR Embedded Workbench", "Makefile"):
        assert f"{ide}  Removed" in out, ide


def test_a_library_of_headers_only_comes_out_too(library, project, nobody, no_network):
    root = _every_ide(project)
    before = _snapshot(root)
    _install(library(once=[], sources=()), "--project", root, "--dir", "Libs/demo")

    assert cli.main(["--uninstall", "demo", "--project", str(root)]) == 0

    assert _snapshot(root) == before


def test_the_other_library_stays_in_every_project_file(library, project, nobody, no_network, tmp_path):
    root = _every_ide(project)
    first = library(name="first", headers=("first.h",), sources=("first.c",), once=[],
                    install={"defines": ["SHARED", "FIRST"]}, root=tmp_path / "src" / "first")
    second = library(name="second", headers=("second.h",), sources=("second.c",), once=[],
                     install={"defines": ["SHARED"]}, root=tmp_path / "src" / "second")
    # Folders that start the same, so only the one taken out is matched.
    _install(second, "--project", root, "--dir", "Libs/drv2")
    only_second = _snapshot(root)
    _install(first, "--project", root, "--dir", "Libs/drv")

    assert cli.main(["--uninstall", "first", "--project", str(root)]) == 0

    assert _snapshot(root) == only_second


def test_a_group_the_user_renamed_keeps_its_name_and_loses_its_files(library, project, nobody, no_network):
    root = project(keil=True)
    _install(library(once=[]), "--project", root, "--dir", "Libs/demo")
    path = root / "MDK" / "Proj.uvprojx"
    path.write_text(path.read_text(encoding="utf-8").replace("<GroupName>demo<", "<GroupName>Drivers/demo<"),
                    encoding="utf-8")

    assert cli.main(["--uninstall", "demo", "--project", str(root)]) == 0

    text = path.read_text(encoding="utf-8")
    assert "<GroupName>Drivers/demo</GroupName>" in text
    assert "demo.c" not in text


def test_the_cmakelists_in_the_library_folder_goes_with_it(library, project, nobody, no_network):
    root = project(cmake=True)
    _install(library(once=[]), "--project", root, "--dir", "Libs/demo")
    assert (root / "Libs" / "demo" / "CMakeLists.txt").is_file()

    assert cli.main(["--uninstall", "demo", "--project", str(root)]) == 0

    assert not (root / "Libs" / "demo").exists()


def test_a_half_written_block_is_left_for_the_user(library, project, nobody, no_network, capsys):
    root = project(cmake=True)
    _install(library(once=[]), "--project", root, "--dir", "Libs/demo")
    path = root / "CMakeLists.txt"
    text = path.read_text(encoding="utf-8")
    broken = text.replace("# <<< stm32-installer: demo <<<", "")
    path.write_text(broken, encoding="utf-8")

    assert cli.main(["--uninstall", "demo", "--project", str(root)]) == 0

    assert path.read_text(encoding="utf-8") == broken
    assert "half written stm32-installer block for demo" in capsys.readouterr().out


def test_a_project_file_that_cannot_be_read_does_not_stop_the_files_going(
        library, project, nobody, no_network, monkeypatch, capsys):
    from stm32_installer.ide import keil

    root = project(keil=True)
    _install(library(once=[]), "--project", root, "--dir", "Libs/demo")

    def broken(*args):
        raise ValueError("unreadable")

    monkeypatch.setattr(keil, "remove", broken)

    assert cli.main(["--uninstall", "demo", "--project", str(root)]) == 0

    assert not (root / "Libs" / "demo").exists()
    out = capsys.readouterr().out
    assert "Could not update the project automatically: unreadable" in out
    assert "Take demo out by hand" in out


def test_nothing_of_the_library_left_says_so(library, project, nobody, no_network, capsys):
    root = project(makefile=True)
    _install(library(once=[]), "--project", root, "--dir", "Libs/demo")
    (root / "Makefile").write_text("C_SOURCES = \\\nCore/Src/main.c\n\nC_INCLUDES = \\\n-ICore/Inc\n",
                                   encoding="utf-8")

    assert cli.main(["--uninstall", "demo", "--project", str(root)]) == 0

    assert "The Makefile has nothing of demo." in capsys.readouterr().out


SOURCE_ENTRIES = (
    "\t\t\t<sourceEntries>\n"
    "\t\t\t\t<entry flags=\"VALUE_WORKSPACE_PATH|RESOLVED\" kind=\"sourcePath\" name=\"Core\"/>\n"
    "\t\t\t\t<entry flags=\"VALUE_WORKSPACE_PATH|RESOLVED\" kind=\"sourcePath\" name=\"Drivers\"/>\n"
    "\t\t\t</sourceEntries>\n"
)


def test_a_named_source_folder_is_added_and_taken_out_again(library, project, nobody, no_network):
    """A .cproject that lists its source folders compiles only those, so the library's is added."""
    root = project(cubeide=True)
    path = root / ".cproject"
    text = path.read_text(encoding="utf-8").replace("\t\t\t</toolChain>\n", "\t\t\t</toolChain>\n" + SOURCE_ENTRIES)
    path.write_bytes(text.encode("utf-8"))

    _install(library(once=[]), "--project", root, "--dir", "Libs/demo")
    assert path.read_text(encoding="utf-8").count('kind="sourcePath" name="Libs/demo"') == 2

    assert cli.main(["--uninstall", "demo", "--project", str(root)]) == 0

    assert path.read_bytes() == text.encode("utf-8")
