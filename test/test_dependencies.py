"""
Tests for a library that needs other libraries.

A library lists them under requires.libraries, as "osal" or "osal >= 1.1.0".
These tests pin down that what is needed goes in first, that what is already
in the project is left alone with nobody asked anything, that what is too old
is updated where it is, and that a library that cannot be had stops the run
before anything is written.
"""

import zipfile

import pytest

from stm32_installer import cli, download, installer, manifest


def _zip(folder, archive, top):
    """Zip a library the way GitHub's Download ZIP does: under one top folder."""
    archive.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(archive, "w") as bundle:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                bundle.write(path, f"{top}/{path.relative_to(folder).as_posix()}")

    return archive


@pytest.fixture
def github(monkeypatch):
    """
    Stand in for GitHub with libraries on disk, and remember what was fetched.

    A source the test did not put there is a failed download, which is what a
    machine without the internet gets.
    """
    repos = {}
    fetched = []

    def fake_fetch(source, ref="master", destination=None):
        fetched.append((source, ref))

        if source not in repos:
            raise download.DownloadError(f"could not reach GitHub for {source}")

        return repos[source]

    monkeypatch.setattr(download, "fetch", fake_fetch)

    return repos, fetched


@pytest.fixture
def no_question(monkeypatch):
    """Fail the test if the folder question is asked for any of the names given."""
    asked = []
    real = cli._ask_folder

    def watch(names):
        def ask(default, name=None):
            asked.append(name)

            if name in names:
                raise AssertionError(f"asked where to put {name}, which needed no question")

            return real(default, name)

        monkeypatch.setattr(cli, "_ask_folder", ask)
        return asked

    return watch


def _lib(library, where, name, version="1.0.0", needs=None):
    """A library on disk, with a header named after it and what it needs."""
    requires = {"libraries": needs} if needs else None

    return library(
        name=name,
        version=version,
        headers=[f"inc/{name}.h"],
        sources=[],
        once=[{"from": "template/demo_config.h", "to": f"{name}_config.h"}],
        requires=requires,
        root=where / name,
    )


# ----------------------------------------------------------------------------
# The manifest: how a dependency is written.
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, source, name, minimum",
    [
        ("osal", "osal", "osal", None),
        ("osal >= 1.1.0", "osal", "osal", (1, 1, 0)),
        ("osal>=1.1.0", "osal", "osal", (1, 1, 0)),
        ("someone/osal >= 2.0.0", "someone/osal", "osal", (2, 0, 0)),
    ],
)
def test_a_dependency_is_a_name_and_an_oldest_version(text, source, name, minimum):
    dependency = manifest.Dependency(text)

    assert dependency.source == source
    assert dependency.name == name
    assert dependency.minimum == minimum


@pytest.mark.parametrize("text", ["osal > 1.0.0", "osal >= 1.0", "osal >= one", "osal 1.0.0", ""])
def test_a_dependency_written_any_other_way_is_refused(text):
    with pytest.raises(manifest.ManifestError):
        manifest.Dependency(text)


def test_a_minimum_version_is_compared_as_numbers():
    dependency = manifest.Dependency("osal >= 1.2.0")

    assert dependency.satisfied_by("1.10.0"), "1.10 is newer than 1.2"
    assert dependency.satisfied_by("1.2.0")
    assert not dependency.satisfied_by("1.1.9")
    assert not dependency.satisfied_by(None), "an unknown version cannot be shown new enough"
    assert manifest.Dependency("osal").satisfied_by(None), "with no minimum, anything will do"


# ----------------------------------------------------------------------------
# Installing what is needed.
# ----------------------------------------------------------------------------


def test_what_a_library_needs_is_installed_first(library, project, tmp_path, github, capsys):
    repos, fetched = github
    root = project(cmake=True)
    repos["nimaltd/ee24"] = _lib(library, tmp_path / "gh", "ee24", needs=["osal >= 1.0.0"])
    repos["osal"] = _lib(library, tmp_path / "gh", "osal")

    code = cli.main(["nimaltd/ee24", "--project", str(root), "--dir", "ee24"])
    out = capsys.readouterr().out
    known = installer.installed_libraries(root)

    assert code == 0
    assert fetched == [("nimaltd/ee24", "master"), ("osal", "master")]
    assert (root / "osal" / "osal.h").is_file(), "the folder question defaults to the name"
    assert (root / "ee24" / "ee24.h").is_file()
    assert known["osal"]["folder"] == "osal" and known["ee24"]["folder"] == "ee24"
    assert out.index("Installing osal first") < out.index('#include "osal.h"') < out.index('#include "ee24.h"')
    assert not repos["osal"].exists(), "the download of osal was left behind"


def test_what_is_already_there_is_kept_and_nobody_is_asked(
    library, project, tmp_path, github, no_question, capsys
):
    repos, fetched = github
    root = project(cmake=True)
    osal = _lib(library, tmp_path / "disk", "osal", version="1.2.0")

    assert cli.main([str(osal), "--project", str(root), "--dir", "Libs/osal"]) == 0
    capsys.readouterr()

    asked = no_question({"osal"})
    repos["nimaltd/ee24"] = _lib(library, tmp_path / "gh", "ee24", needs=["osal >= 1.1.0"])

    code = cli.main(["nimaltd/ee24", "--project", str(root), "--dir", "ee24"])
    out = capsys.readouterr().out

    assert code == 0
    assert "osal 1.2.0 is already in this project, kept" in out
    assert ("osal", "master") not in fetched, "fetched a library that was already there"
    assert not (root / "osal").exists(), "a second copy of osal went in"
    assert installer.installed_libraries(root)["osal"]["folder"] == "Libs/osal"
    assert asked == []


def test_a_copy_given_on_the_command_line_is_installed_even_when_one_will_do(
    library, project, tmp_path, github, no_question
):
    """The user asked for it, so it goes in, as an update where the old one is."""
    root = project(cmake=True)
    old = _lib(library, tmp_path / "v1", "osal", version="1.0.0")

    assert cli.main([str(old), "--project", str(root), "--dir", "Libs/osal"]) == 0

    no_question({"osal"})
    ee24 = _lib(library, tmp_path / "disk", "ee24", needs=["osal"])
    newer = _lib(library, tmp_path / "v2", "osal", version="1.1.0")

    assert cli.main([str(ee24), str(newer), "--project", str(root)]) == 0

    known = installer.installed_libraries(root)
    assert known["osal"]["version"] == "1.1.0", "the copy given was not installed"
    assert known["osal"]["folder"] == "Libs/osal"


def test_what_is_too_old_is_updated_where_it_is(
    library, project, tmp_path, github, no_question, capsys
):
    repos, _ = github
    root = project(cmake=True)
    old = _lib(library, tmp_path / "v1", "osal", version="1.0.0")

    assert cli.main([str(old), "--project", str(root), "--dir", "Libs/osal"]) == 0
    (root / "Libs" / "osal" / "osal_config.h").write_text("#define MINE 1\n", encoding="utf-8")
    capsys.readouterr()

    no_question({"osal"})
    repos["osal"] = _lib(library, tmp_path / "v2", "osal", version="1.1.0")
    ee24 = _lib(library, tmp_path / "disk", "ee24", needs=["osal >= 1.1.0"])

    code = cli.main([str(ee24), "--project", str(root), "--dir", "ee24"])
    out = capsys.readouterr().out
    known = installer.installed_libraries(root)

    assert code == 0
    assert "Updating osal first" in out
    assert known["osal"]["version"] == "1.1.0"
    assert known["osal"]["folder"] == "Libs/osal", "the update went somewhere else"
    assert not (root / "osal").exists()
    assert (root / "Libs" / "osal" / "osal_config.h").read_text(encoding="utf-8") == "#define MINE 1\n", \
        "the user's settings were overwritten"


def test_what_cannot_be_had_stops_the_run_before_anything_is_written(
    library, project, tmp_path, github, capsys
):
    root = project(cmake=True)
    before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
    ee24 = _lib(library, tmp_path / "disk", "ee24", needs=["osal"])

    code = cli.main([str(ee24), "--project", str(root), "--dir", "ee24"])
    err = capsys.readouterr().err

    assert code == 2
    assert "ee24 needs osal" in err
    assert "give both zips on one line" in err
    assert sorted(p.relative_to(root).as_posix() for p in root.rglob("*")) == before, \
        "the project was changed by a run that could not finish"


def test_the_newest_to_be_had_must_be_new_enough(library, project, tmp_path, github, capsys):
    repos, _ = github
    root = project(cmake=True)
    repos["osal"] = _lib(library, tmp_path / "gh", "osal", version="1.0.0")
    ee24 = _lib(library, tmp_path / "disk", "ee24", needs=["osal >= 2.0.0"])

    code = cli.main([str(ee24), "--project", str(root), "--dir", "ee24"])

    assert code == 2
    assert "the newest osal to be had is 1.0.0" in capsys.readouterr().err
    assert installer.installed_libraries(root) == {}


def test_zips_given_together_install_without_the_internet(library, project, tmp_path, github, capsys):
    _, fetched = github
    root = project(cmake=True)
    ee24 = _zip(_lib(library, tmp_path / "src", "ee24", needs=["osal"]),
                tmp_path / "Downloads" / "ee24-master.zip", "ee24-master")
    osal = _zip(_lib(library, tmp_path / "src", "osal"),
                tmp_path / "Downloads" / "osal-master.zip", "osal-master")

    code = cli.main([str(ee24), str(osal), "--project", str(root)])
    out = capsys.readouterr().out

    assert code == 0
    assert fetched == [], "went online for a library given as a zip"
    assert (root / "osal" / "osal.h").is_file() and (root / "ee24" / "ee24.h").is_file()
    assert out.index('#include "osal.h"') < out.index('#include "ee24.h"'), "osal did not go in first"
    assert out.count('#include "osal.h"') == 1, "osal went in twice"


def test_what_a_needed_library_needs_goes_in_before_it(library, project, tmp_path, github, capsys):
    repos, _ = github
    root = project(cmake=True)
    repos["osal"] = _lib(library, tmp_path / "gh", "osal", needs=["base"])
    repos["base"] = _lib(library, tmp_path / "gh", "base")
    ee24 = _lib(library, tmp_path / "disk", "ee24", needs=["osal"])

    code = cli.main([str(ee24), "--project", str(root), "--dir", "ee24"])
    out = capsys.readouterr().out

    assert code == 0
    assert out.index('#include "base.h"') < out.index('#include "osal.h"') < out.index('#include "ee24.h"')


def test_a_library_two_others_need_goes_in_once(library, project, tmp_path, github, capsys):
    repos, fetched = github
    root = project(cmake=True)
    repos["osal"] = _lib(library, tmp_path / "gh", "osal")
    ee24 = _lib(library, tmp_path / "disk", "ee24", needs=["osal"])
    spif = _lib(library, tmp_path / "disk", "spif", needs=["osal"])

    code = cli.main([str(ee24), str(spif), "--project", str(root)])
    out = capsys.readouterr().out

    assert code == 0
    assert fetched.count(("osal", "master")) == 1
    assert out.count('#include "osal.h"') == 1
    assert (root / "spif" / "spif.h").is_file()


def test_libraries_that_need_each_other_are_refused(library, project, tmp_path, github, capsys):
    root = project(cmake=True)
    first = _lib(library, tmp_path / "disk", "first", needs=["second"])
    second = _lib(library, tmp_path / "disk", "second", needs=["first"])

    code = cli.main([str(first), str(second), "--project", str(root)])

    assert code == 2
    assert "first -> second -> first" in capsys.readouterr().err
    assert installer.installed_libraries(root) == {}


def test_dir_is_refused_with_more_than_one_library(library, project, tmp_path, github, capsys):
    root = project(cmake=True)
    one = _lib(library, tmp_path / "disk", "one")
    two = _lib(library, tmp_path / "disk", "two")

    code = cli.main([str(one), str(two), "--project", str(root), "--dir", "x"])

    assert code == 2
    assert "--dir names the folder for one library" in capsys.readouterr().err


def test_an_update_offers_the_folder_the_library_is_already_in(library, project, tmp_path, github):
    """It used to offer the library's name, which put a second copy in ./demo."""
    root = project(cmake=True)
    first = _lib(library, tmp_path / "v1", "demo")
    second = _lib(library, tmp_path / "v2", "demo", version="1.1.0")

    assert cli.main([str(first), "--project", str(root), "--dir", "Libs/demo"]) == 0
    assert cli.main([str(second), "--project", str(root)]) == 0

    assert installer.installed_libraries(root)["demo"]["version"] == "1.1.0"
    assert installer.installed_libraries(root)["demo"]["folder"] == "Libs/demo"
    assert not (root / "demo").exists()
