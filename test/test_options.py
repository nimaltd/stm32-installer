"""
Tests for options: parts of a library the user chooses at install.

spif is the reason they exist. Its littlefs port is two files of spif's own
that only make sense with littlefs, a library of its own. Asked at the first
install, yes brings both, and no brings neither. The answer is kept, so an
update does not ask again, and --with or --without changes it later.
"""

import io
import json

import pytest

from stm32_installer import cli, download, installer, manifest

LFS = {
    "description": "LittleFS file system on the flash",
    "libraries": ["fsx"],
    "files": {"headers": ["inc/demo_lfs.h"], "sources": ["src/demo_lfs.c"]},
}


def _demo(library, root=None, options=None, **kwargs):
    """A library with the littlefs option, on disk."""
    return library(root=root, options=options or {"lfs": LFS}, **kwargs)


def _fsx(library, tmp_path):
    """The library the option brings."""
    return library(name="fsx", headers=("inc/fsx.h",), sources=("src/fsx.c",), once=[],
                   root=tmp_path / "fsx")


@pytest.fixture
def no_network(monkeypatch):
    """Fail loudly if anything tries to reach GitHub."""

    def refuse(*args, **kwargs):
        raise AssertionError("went online for something that was on disk")

    monkeypatch.setattr(download, "fetch", refuse)


class _Terminal:
    """stdin or stdout, a terminal or not."""

    def __init__(self, tty):
        self.tty = tty
        self.text = io.StringIO()

    def isatty(self):
        return self.tty

    def write(self, text):
        return self.text.write(text)

    def flush(self):
        pass


@pytest.fixture
def answers(monkeypatch):
    """
    Someone at the keyboard, giving these answers to the option questions.

    The folder questions get an empty answer, which takes the default. Every
    option question is recorded, so a test can say none was asked.
    """
    asked = []

    def give(**replies):
        # Only what is asked from here on.
        asked.clear()
        monkeypatch.setattr(cli.sys, "stdin", _Terminal(tty=True))

        def fake_input(prompt=""):
            if "Add it?" in prompt:
                name = prompt.split()[0]
                asked.append(name)
                return replies.get(name, "")

            return ""

        monkeypatch.setattr(cli, "input", fake_input, raising=False)

        return asked

    return give


@pytest.fixture
def nobody(monkeypatch):
    """No one at the keyboard: a script or a build server."""

    def refuse(*args, **kwargs):
        raise AssertionError("opened the console with nobody at it")

    monkeypatch.setattr(cli.sys, "stdin", _Terminal(tty=False))
    monkeypatch.setattr(cli.sys, "stdout", _Terminal(tty=False))
    monkeypatch.setattr(cli, "open", refuse, raising=False)


def _record(root):
    return json.loads((root / installer.RECORD_NAME).read_text(encoding="utf-8"))["libraries"]


# ----------------------------------------------------------------------------
# The manifest.
# ----------------------------------------------------------------------------


def test_the_manifest_reads_the_options(library):
    lib = manifest.load(_demo(library))
    option = lib.options["lfs"]

    assert option.description == "LittleFS file system on the flash"
    assert [d.name for d in option.libraries] == ["fsx"]
    assert [e.source.as_posix() for e in option.code_files] == ["inc/demo_lfs.h", "src/demo_lfs.c"]


def test_nothing_is_taken_until_it_is_chosen(library):
    """Whatever installs without asking gets the library without its options."""
    lib = manifest.load(_demo(library))

    assert lib.chosen == []
    assert [e.destination for e in lib.code_files] == ["demo.h", "demo.c"]
    assert lib.build_sources == ["demo.c"]
    assert lib.dependencies == []


def test_a_chosen_option_brings_its_files_and_its_libraries(library):
    lib = manifest.load(_demo(library))

    lib.choose(["lfs"])

    assert [e.destination for e in lib.code_files] == ["demo.h", "demo.c", "demo_lfs.h", "demo_lfs.c"]
    assert lib.build_sources == ["demo.c", "demo_lfs.c"]
    assert [d.name for d in lib.dependencies] == ["fsx"]


def test_a_chosen_option_puts_its_header_folder_on_the_include_path(library):
    options = {"lfs": dict(LFS, files={"headers": ["src/port/demo_lfs.h"], "sources": ["src/port/demo_lfs.c"]})}
    lib = manifest.load(_demo(library, options=options, install={"layout": "mirror"}))

    assert lib.include_dirs == ["inc"]

    lib.choose(["lfs"])

    assert lib.include_dirs == ["inc", "src/port"]


def test_choosing_an_option_the_library_does_not_have_is_refused(library):
    lib = manifest.load(_demo(library))

    with pytest.raises(manifest.ManifestError, match="no option called lfs2"):
        lib.choose(["lfs2"])


def test_an_option_file_that_is_not_there_is_refused(library):
    root = _demo(library)
    (root / "src" / "demo_lfs.c").unlink()

    with pytest.raises(manifest.ManifestError, match="demo_lfs.c"):
        manifest.load(root)


@pytest.mark.parametrize("options", [
    {"lfs": dict(LFS, files={"sources": ["src/demo.c"]})},                         # the library's own
    {"lfs": LFS, "fat": dict(LFS, files={"sources": ["src/demo_lfs.c"]})},         # another option's
])
def test_a_file_is_the_library_s_or_one_option_s_never_both(options, library):
    """Turning the option off would remove a file the library still needs."""
    with pytest.raises(manifest.ManifestError, match="both in an option"):
        manifest.load(_demo(library, options=options))


@pytest.mark.parametrize("name", ["LFS", "little fs", "2lfs", "-lfs"])
def test_an_option_name_that_cannot_be_typed_plainly_is_refused(name, library):
    with pytest.raises(manifest.ManifestError, match="--with"):
        manifest.load(_demo(library, options={name: LFS}))


def test_an_option_that_is_not_a_mapping_is_refused(library):
    with pytest.raises(manifest.ManifestError, match="options.lfs"):
        manifest.load(_demo(library, options={"lfs": "yes"}))


def test_an_option_without_a_description_is_warned_about(library):
    lib = manifest.load(_demo(library, options={"lfs": {"files": {"sources": ["src/demo_lfs.c"]}}}))

    assert any("description" in warning for warning in lib.warnings)


def test_a_download_fetches_the_files_of_every_option():
    """Chosen or not: the question comes after the download, not before it."""
    data = {"files": {"headers": ["inc/demo.h"]}, "options": {"lfs": LFS, "odd": "nonsense"}}

    entries = download._listed_entries(data)

    assert "inc/demo_lfs.h" in entries
    assert "src/demo_lfs.c" in entries


# ----------------------------------------------------------------------------
# Installing.
# ----------------------------------------------------------------------------


def test_an_option_taken_is_installed_and_recorded(library, tmp_path):
    root = tmp_path / "Proj"
    lib = manifest.load(_demo(library))
    lib.choose(["lfs"])

    installer.install_to(lib, root / "demo", project_root=root)

    assert (root / "demo" / "demo_lfs.c").is_file()
    assert _record(root)["demo"]["options"] == {"lfs": True}


def test_an_option_turned_off_takes_its_files_out(library, tmp_path):
    root = tmp_path / "Proj"
    lib = manifest.load(_demo(library))
    lib.choose(["lfs"])
    installer.install_to(lib, root / "demo", project_root=root)

    lib = manifest.load(_demo(library))
    result = installer.install_to(lib, root / "demo", project_root=root)

    assert not (root / "demo" / "demo_lfs.c").exists()
    assert not (root / "demo" / "demo_lfs.h").exists()
    assert (root / "demo" / "demo.c").is_file()
    assert sorted(p.name for p in result.dropped) == ["demo_lfs.c", "demo_lfs.h"]
    assert _record(root)["demo"]["options"] == {"lfs": False}


def test_in_place_an_option_not_taken_leaves_no_file_behind(library, tmp_path):
    """CubeIDE compiles every .c under the project, so one left there is built."""
    root = tmp_path / "Proj"
    folder = _demo(library, root=root / "demo", install={"layout": "mirror"})
    lib = manifest.load(folder)

    result = installer.install_in_place(lib, project_root=root)

    assert not (folder / "src" / "demo_lfs.c").exists()
    assert not (folder / "inc" / "demo_lfs.h").exists()
    assert (folder / "src" / "demo.c").is_file()
    assert "src/demo_lfs.c" in result.removed


def test_in_place_an_option_taken_stays(library, tmp_path):
    root = tmp_path / "Proj"
    folder = _demo(library, root=root / "demo", install={"layout": "mirror"})
    lib = manifest.load(folder)
    lib.choose(["lfs"])

    installer.install_in_place(lib, project_root=root)

    assert (folder / "src" / "demo_lfs.c").is_file()


# ----------------------------------------------------------------------------
# The command line.
# ----------------------------------------------------------------------------


@pytest.mark.parametrize("reply", ["y", "Y", "yes"])
def test_yes_brings_the_option_and_the_library_it_needs(reply, library, project, tmp_path, answers, no_network):
    root = project(keil=True)
    asked = answers(lfs=reply)

    code = cli.main([str(_demo(library)), str(_fsx(library, tmp_path)), "--project", str(root)])

    assert code == 0
    assert asked == ["lfs"]
    assert (root / "demo" / "demo_lfs.c").is_file()
    assert (root / "fsx" / "fsx.c").is_file()
    assert "demo_lfs.c" in (root / "MDK" / "Proj.uvprojx").read_text(encoding="utf-8")


def test_the_option_alone_brings_its_library(library, project, tmp_path, nobody, monkeypatch):
    """Not named on the command line, so only the option can have asked for it."""
    root = project(cmake=True)
    fetched = []
    fsx = _fsx(library, tmp_path)

    def fetch(source, *args, **kwargs):
        fetched.append(source)
        return fsx

    monkeypatch.setattr(download, "fetch", fetch)

    assert cli.main([str(_demo(library)), "--project", str(root), "--dir", "demo", "--with", "lfs"]) == 0
    assert fetched == ["fsx"]
    assert (root / "fsx" / "fsx.c").is_file()


@pytest.mark.parametrize("reply", ["", "n", "no", "maybe"])
def test_anything_but_yes_leaves_the_option_out(reply, library, project, answers, no_network):
    root = project(cmake=True)
    answers(lfs=reply)

    assert cli.main([str(_demo(library)), "--project", str(root), "--dir", "demo"]) == 0
    assert not (root / "demo" / "demo_lfs.c").exists()
    assert not (root / "fsx").exists()
    assert _record(root)["demo"]["options"] == {"lfs": False}


def test_nobody_is_asked_when_nobody_can_answer(library, project, nobody, no_network, capsys):
    root = project(cmake=True)

    assert cli.main([str(_demo(library)), "--project", str(root), "--dir", "demo"]) == 0
    assert not (root / "demo" / "demo_lfs.c").exists()
    assert "no, nobody was asked. Add it with --with lfs" in capsys.readouterr().out


def test_with_takes_the_option_without_a_question(library, project, tmp_path, nobody, no_network):
    root = project(cmake=True)

    code = cli.main([str(_demo(library)), str(_fsx(library, tmp_path)), "--project", str(root), "--with", "lfs"])

    assert code == 0
    assert (root / "demo" / "demo_lfs.c").is_file()
    assert (root / "fsx" / "fsx.c").is_file()


def test_an_update_keeps_the_answer_without_asking_again(library, project, tmp_path, answers, no_network, capsys):
    root = project(cmake=True)
    answers(lfs="y")
    cli.main([str(_demo(library)), str(_fsx(library, tmp_path)), "--project", str(root)])

    asked = answers()
    capsys.readouterr()
    code = cli.main([str(_demo(library, root=tmp_path / "v2")), "--project", str(root)])

    assert code == 0
    assert asked == [], "asked again on an update"
    assert (root / "demo" / "demo_lfs.c").is_file()
    assert "yes, as before. Change it with --without lfs" in capsys.readouterr().out


def test_without_takes_the_option_out_and_leaves_its_library(library, project, tmp_path, nobody, no_network, capsys):
    root = project(keil=True)
    cli.main([str(_demo(library)), str(_fsx(library, tmp_path)), "--project", str(root), "--with", "lfs"])
    capsys.readouterr()

    code = cli.main([str(_demo(library, root=tmp_path / "v2")), "--project", str(root), "--without", "lfs"])
    out = capsys.readouterr().out

    assert code == 0
    assert not (root / "demo" / "demo_lfs.c").exists()
    assert (root / "fsx" / "fsx.c").is_file(), "the library it brought was removed"
    assert "demo_lfs.c" not in (root / "MDK" / "Proj.uvprojx").read_text(encoding="utf-8")
    assert "option lfs is off" in out
    assert "fsx stays in the project" in out


def test_an_option_new_in_an_update_is_asked_about(library, project, tmp_path, answers, no_network):
    root = project(cmake=True)
    answers()
    cli.main([str(library()), "--project", str(root), "--dir", "demo"])

    asked = answers(lfs="")
    cli.main([str(_demo(library, root=tmp_path / "v2")), "--project", str(root), "--dir", "demo"])

    assert asked == ["lfs"]


def test_an_option_no_library_has_is_refused_before_anything(library, project, nobody, no_network, capsys):
    root = project(cmake=True)

    code = cli.main([str(_demo(library)), "--project", str(root), "--dir", "demo", "--with", "lsf"])

    assert code == 2
    assert not (root / "demo").exists()
    assert "No option called lsf. What is installed here has: lfs." in capsys.readouterr().err


def test_with_and_without_the_same_option_is_refused(library, project, nobody, no_network, capsys):
    root = project(cmake=True)

    code = cli.main([str(_demo(library)), "--project", str(root), "--dir", "demo",
                     "--with", "lfs", "--without", "lfs"])

    assert code == 2
    assert not (root / "demo").exists()


def test_a_library_updated_because_another_needs_it_keeps_its_options(
    library, project, tmp_path, nobody, monkeypatch
):
    """Fetched as a dependency, it must not lose the option the user took."""
    root = project(cmake=True)
    extra = {"x": {"description": "extra", "files": {"sources": ["src/fsx_x.c"]}}}
    old = library(name="fsx", version="1.0.0", headers=("inc/fsx.h",), sources=("src/fsx.c",), once=[],
                  options=extra, root=tmp_path / "fsx1")
    assert cli.main([str(old), "--project", str(root), "--dir", "fsx", "--with", "x"]) == 0

    new = library(name="fsx", version="2.0.0", headers=("inc/fsx.h",), sources=("src/fsx.c",), once=[],
                  options=extra, root=tmp_path / "fsx2")
    monkeypatch.setattr(download, "fetch", lambda *args, **kwargs: new)
    demo = library(requires={"libraries": ["fsx >= 2.0.0"]}, root=tmp_path / "demo")

    assert cli.main([str(demo), "--project", str(root), "--dir", "demo"]) == 0
    assert _record(root)["fsx"]["version"] == "2.0.0"
    assert (root / "fsx" / "fsx_x.c").is_file(), "the update dropped the option"


def test_a_library_brought_in_keeps_its_options_without_a_question(library, project, tmp_path, nobody, capsys):
    """The flags are for what was named, so one brought in only keeps its answer."""
    root = project(cmake=True)
    lib = manifest.load(_demo(library))
    root.joinpath(installer.RECORD_NAME).write_text(
        json.dumps({"libraries": {"demo": {"folder": "demo", "options": {"lfs": True}}}}), encoding="utf-8"
    )

    cli._choose_options(lib, root)
    assert lib.chosen == ["lfs"]

    lib = manifest.load(_demo(library, root=tmp_path / "v2"))
    cli._choose_options(lib, tmp_path / "elsewhere")

    assert lib.chosen == []
    assert "Add it with: stm32-installer demo --with lfs" in capsys.readouterr().out
