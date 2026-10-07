"""Tests for copying a library into a project."""

import json

from stm32_installer import installer, manifest


def test_code_and_config_land_in_the_folder(library, tmp_path):
    lib = manifest.load(library())
    destination = tmp_path / "Proj" / "demo"

    result = installer.install_to(lib, destination)

    assert (destination / "demo.h").is_file()
    assert (destination / "demo.c").is_file()
    assert (destination / "demo_config.h").is_file()
    assert len(result.created) == 1


def test_files_land_flat_not_in_inc_and_src(library, tmp_path):
    """One folder means one include path, which is the whole point."""
    lib = manifest.load(library())
    destination = tmp_path / "Proj" / "demo"

    installer.install_to(lib, destination)

    assert not (destination / "inc").exists()
    assert not (destination / "src").exists()


def test_an_existing_config_is_never_overwritten(library, tmp_path):
    """The user's settings live in that file. Losing them is the worst outcome."""
    lib = manifest.load(library())
    destination = tmp_path / "Proj" / "demo"

    installer.install_to(lib, destination)
    (destination / "demo_config.h").write_text("#define DEMO_SIZE 64\n", encoding="utf-8")

    result = installer.install_to(lib, destination)

    assert (destination / "demo_config.h").read_text(encoding="utf-8") == "#define DEMO_SIZE 64\n"
    assert result.kept
    assert not result.created
    assert result.was_update


def test_code_is_replaced_on_a_second_install(library, tmp_path):
    """Updating has to actually update, or there is no point to it."""
    lib = manifest.load(library())
    destination = tmp_path / "Proj" / "demo"

    installer.install_to(lib, destination)
    (destination / "demo.c").write_text("/* stale */\n", encoding="utf-8")

    installer.install_to(lib, destination)

    assert (destination / "demo.c").read_text(encoding="utf-8") == "/* source */\n"


def test_the_notice_travels_with_the_code(library, tmp_path):
    """The licence requires it, and it is what carries the attribution."""
    lib = manifest.load(library())
    destination = tmp_path / "Proj" / "demo"

    installer.install_to(lib, destination)

    assert (destination / "NOTICE").is_file()


def test_in_place_removes_the_repository_scaffolding(library, tmp_path):
    """CubeIDE compiles every .c under the project, so test/ must not survive."""
    root = tmp_path / "Proj" / "demo"
    library(root=root, extra_files={"test/test_demo.c": "int main(void){return 0;}\n"})
    (root / ".github").mkdir()
    (root / ".github" / "ci.yml").write_text("on: push\n", encoding="utf-8")
    (root / "CMakeLists.txt").write_text("project(demo)\n", encoding="utf-8")

    lib = manifest.load(root)
    result = installer.install_in_place(lib)

    assert not (root / "test").exists()
    assert not (root / ".github").exists()
    assert not (root / "inc").exists()
    assert not (root / "src").exists()
    assert not (root / "template").exists()
    assert not (root / "installer.yml").exists()
    assert "test" in result.removed


def test_the_template_folder_goes_but_the_copy_stays(library, tmp_path):
    """The user edits the copy. Leaving the template behind would only confuse."""
    root = tmp_path / "Proj" / "demo"
    library(root=root)

    installer.install_in_place(manifest.load(root))

    assert not (root / "template").exists()
    assert (root / "demo_config.h").is_file()


def test_in_place_keeps_the_licence_files(library, tmp_path):
    root = tmp_path / "Proj" / "demo"
    library(root=root, extra_files={"LICENSE.md": "Apache\n"})

    installer.install_in_place(manifest.load(root))

    assert (root / "LICENSE.md").is_file()
    assert (root / "NOTICE").is_file()


def test_cleanup_leaves_files_the_user_added(library, tmp_path):
    """Deleting a fixed list, not everything unrecognised, is what makes this safe."""
    root = tmp_path / "Proj" / "demo"
    library(root=root)
    (root / "my_notes.txt").write_text("mine\n", encoding="utf-8")

    installer.install_in_place(manifest.load(root))

    assert (root / "my_notes.txt").is_file()


def test_the_record_says_what_was_installed(library, tmp_path):
    lib = manifest.load(library())
    project_root = tmp_path / "Proj"

    installer.install_to(lib, project_root / "demo", project_root=project_root)

    record = json.loads((project_root / installer.RECORD_NAME).read_text(encoding="utf-8"))
    entry = record["libraries"]["demo"]

    assert entry["version"] == "1.0.0"
    assert entry["folder"] == "demo"
    assert "demo/demo.c" in entry["files"]


def test_a_damaged_record_does_not_break_an_install(library, tmp_path):
    lib = manifest.load(library())
    project_root = tmp_path / "Proj"
    project_root.mkdir()
    (project_root / installer.RECORD_NAME).write_text("{ not json", encoding="utf-8")

    installer.install_to(lib, project_root / "demo", project_root=project_root)

    assert installer.installed_libraries(project_root)["demo"]["version"] == "1.0.0"


def test_installed_libraries_is_empty_for_an_untouched_project(tmp_path):
    assert installer.installed_libraries(tmp_path) == {}


def test_mirror_layout_survives_the_cleanup(library, tmp_path):
    """
    The regression that matters most here.

    A mirror layout leaves files in inc/ and src/, and both of those are on the
    cleanup list. Matching only on file names installed four files and then
    deleted every one of them, leaving a generated CMakeLists.txt pointing at
    nothing.
    """
    root = tmp_path / "Proj" / "big"
    library(
        root=root,
        headers=["inc/big.h", "inc/port/spi.h"],
        sources=["src/big.c", "src/port/spi.c"],
        once=[{"from": "template/big_config.h"}],
        extra_files={"template/big_config.h": "#define N 1\n", "test/test_big.c": "int main(void){}\n"},
        install={"layout": "mirror"},
    )

    installer.install_in_place(manifest.load(root))

    assert (root / "inc" / "big.h").is_file()
    assert (root / "inc" / "port" / "spi.h").is_file()
    assert (root / "src" / "big.c").is_file()
    assert (root / "src" / "port" / "spi.c").is_file()
    assert (root / "big_config.h").is_file()

    # The repository scaffolding still has to go, or CubeIDE compiles the tests.
    assert not (root / "test").exists()
    assert not (root / "template").exists()
    assert not (root / "installer.yml").exists()


def test_mirror_layout_creates_the_subfolders_when_copying_elsewhere(library, tmp_path):
    root = library(
        headers=["inc/demo.h"], sources=["src/demo.c"], install={"layout": "mirror"}
    )
    destination = tmp_path / "Proj" / "demo"

    installer.install_to(manifest.load(root), destination)

    assert (destination / "inc" / "demo.h").is_file()
    assert (destination / "src" / "demo.c").is_file()


# ----------------------------------------------------------------------------
# Updates that change where the files go.
# ----------------------------------------------------------------------------


def _two_versions(library, tmp_path):
    """
    One library twice: first flat, then with its code and config in src/.

    That is what sequencer did after 2.0.0, and the update from one to the
    other is what has to leave a working project behind.
    """
    old = manifest.load(library(root=tmp_path / "v1", headers=["src/demo.h"], sources=["src/demo.c"]))
    new = manifest.load(
        library(
            root=tmp_path / "v2",
            headers=["src/demo.h"],
            sources=["src/demo.c"],
            once=[{"from": "template/demo_config.h", "to": "src/demo_config.h"}],
            install={"layout": "mirror"},
        )
    )

    return old, new


def _resolved(pairs):
    """Moved pairs with both ends resolved, since a temp path can come back in another form."""
    return [(a.resolve(), b.resolve()) for a, b in pairs]


def test_an_update_carries_the_users_config_to_its_new_place(library, tmp_path):
    """
    The user's settings follow the file, and no fresh default is made in its way.

    A default created in src/ would sit beside the header and be found first,
    so the user's own settings would stop applying without a word.
    """
    old, new = _two_versions(library, tmp_path)
    project = tmp_path / "Proj"
    destination = project / "demo"

    installer.install_to(old, destination, project_root=project)
    (destination / "demo_config.h").write_text("#define DEMO_SIZE 64\n", encoding="utf-8")

    result = installer.install_to(new, destination, project_root=project)

    assert (destination / "src" / "demo_config.h").read_text(encoding="utf-8") == "#define DEMO_SIZE 64\n"
    assert not (destination / "demo_config.h").exists()
    assert _resolved(result.moved) == _resolved(
        [(destination / "demo_config.h", destination / "src" / "demo_config.h")]
    )
    assert result.created == []
    assert result.was_update


def test_an_update_removes_what_the_new_version_no_longer_ships(library, tmp_path):
    """Left behind, the old demo.c sits beside src/demo.c and CubeIDE compiles both."""
    old, new = _two_versions(library, tmp_path)
    project = tmp_path / "Proj"
    destination = project / "demo"

    installer.install_to(old, destination, project_root=project)
    (destination / "my_notes.txt").write_text("mine\n", encoding="utf-8")

    result = installer.install_to(new, destination, project_root=project)

    assert not (destination / "demo.h").exists()
    assert not (destination / "demo.c").exists()
    assert (destination / "src" / "demo.c").is_file()
    assert (destination / "my_notes.txt").is_file(), "a file the user added was removed"
    assert sorted(p.name for p in result.dropped) == ["demo.c", "demo.h"]

    record = installer.installed_libraries(project)["demo"]

    assert "demo/demo.c" not in record["files"]
    assert "demo/src/demo.c" in record["files"]
    assert record["once"] == ["demo/src/demo_config.h"]


def test_an_untouched_default_gives_way_to_the_users_copy(library, tmp_path):
    """
    An older installer, updating to the new layout, created a default in src/
    and left the user's file where it was. The user's copy takes its place.
    """
    old, new = _two_versions(library, tmp_path)
    project = tmp_path / "Proj"
    destination = project / "demo"

    installer.install_to(old, destination, project_root=project)
    (destination / "demo_config.h").write_text("#define DEMO_SIZE 64\n", encoding="utf-8")
    (destination / "src").mkdir()
    (destination / "src" / "demo_config.h").write_text("#define DEMO_SIZE 8\n", encoding="utf-8")

    installer.install_to(new, destination, project_root=project)

    assert (destination / "src" / "demo_config.h").read_text(encoding="utf-8") == "#define DEMO_SIZE 64\n"


def test_a_config_already_changed_in_its_new_place_is_left_alone(library, tmp_path):
    """Two edited copies: neither is the default, so neither is thrown away."""
    old, new = _two_versions(library, tmp_path)
    project = tmp_path / "Proj"
    destination = project / "demo"

    installer.install_to(old, destination, project_root=project)
    (destination / "demo_config.h").write_text("#define DEMO_SIZE 64\n", encoding="utf-8")
    (destination / "src").mkdir()
    (destination / "src" / "demo_config.h").write_text("#define DEMO_SIZE 32\n", encoding="utf-8")

    result = installer.install_to(new, destination, project_root=project)

    assert (destination / "src" / "demo_config.h").read_text(encoding="utf-8") == "#define DEMO_SIZE 32\n"
    assert (destination / "demo_config.h").read_text(encoding="utf-8") == "#define DEMO_SIZE 64\n"
    assert result.moved == []


def test_installing_into_another_folder_leaves_the_first_copy_alone(library, tmp_path):
    """A second copy somewhere else is the user's choice, not an update of the first."""
    old, new = _two_versions(library, tmp_path)
    project = tmp_path / "Proj"

    installer.install_to(old, project / "demo", project_root=project)
    result = installer.install_to(new, project / "Libs" / "demo", project_root=project)

    assert (project / "demo" / "demo.c").is_file()
    assert (project / "demo" / "demo_config.h").is_file()
    assert result.dropped == []
    assert result.moved == []


def test_an_update_in_place_puts_the_users_config_over_the_template(library, tmp_path):
    """
    The new repository is dropped over the installed folder and installed where
    it stands. Its own template already sits at src/demo_config.h, so without
    the move that template would be kept and the user's settings ignored.
    """
    project = tmp_path / "Proj"
    folder = project / "demo"

    old = manifest.load(library(root=folder, headers=["src/demo.h"], sources=["src/demo.c"]))
    installer.install_in_place(old, project_root=project)
    (folder / "demo_config.h").write_text("#define DEMO_SIZE 64\n", encoding="utf-8")

    new = manifest.load(
        library(
            root=folder,
            headers=["src/demo.h"],
            sources=["src/demo.c"],
            once=[{"from": "src/demo_config.h", "to": "src/demo_config.h"}],
            extra_files={"src/demo_config.h": "#define DEMO_SIZE 8\n"},
            install={"layout": "mirror"},
        )
    )
    installer.install_in_place(new, project_root=project)

    assert (folder / "src" / "demo_config.h").read_text(encoding="utf-8") == "#define DEMO_SIZE 64\n"
    assert not (folder / "demo_config.h").exists()
    assert not (folder / "demo.c").exists()
    assert not (folder / "installer.yml").exists()


def test_an_update_never_deletes_outside_the_library_folder(library, tmp_path):
    """
    The record is a file anyone can edit, and an older tool may have written it.
    Whatever it lists, nothing outside the library's own folder is removed.
    """
    old, new = _two_versions(library, tmp_path)
    project = tmp_path / "Proj"
    main = project / "Core" / "Src" / "main.c"
    main.parent.mkdir(parents=True)
    main.write_text("int main(void) { return 0; }\n", encoding="utf-8")

    installer.install_to(old, project / "demo", project_root=project)
    record_path = project / installer.RECORD_NAME
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["libraries"]["demo"]["files"].append("Core/Src/main.c")
    record_path.write_text(json.dumps(record), encoding="utf-8")

    installer.install_to(new, project / "demo", project_root=project)

    assert main.is_file(), "the user's main.c was deleted"


def test_each_of_the_users_files_moves_to_its_own_place(library, tmp_path):
    """
    A config and a port layer both move. Each keeps its own content.

    The new version lists them in the opposite order to the record, which is
    sorted, so a match on anything but the name would pair them up wrongly.
    """
    extra = {"template/demo_port.c": "/* port */\n"}
    old = manifest.load(
        library(
            root=tmp_path / "v1",
            once=[{"from": "template/demo_config.h"}, {"from": "template/demo_port.c"}],
            extra_files=extra,
        )
    )
    new = manifest.load(
        library(
            root=tmp_path / "v2",
            once=[
                {"from": "template/demo_port.c", "to": "src/demo_port.c"},
                {"from": "template/demo_config.h", "to": "src/demo_config.h"},
            ],
            extra_files=extra,
            install={"layout": "mirror"},
        )
    )
    project = tmp_path / "Proj"
    destination = project / "demo"

    installer.install_to(old, destination, project_root=project)
    (destination / "demo_config.h").write_text("#define DEMO_SIZE 64\n", encoding="utf-8")
    (destination / "demo_port.c").write_text("/* my port */\n", encoding="utf-8")

    installer.install_to(new, destination, project_root=project)

    assert (destination / "src" / "demo_config.h").read_text(encoding="utf-8") == "#define DEMO_SIZE 64\n"
    assert (destination / "src" / "demo_port.c").read_text(encoding="utf-8") == "/* my port */\n"


def test_a_folder_an_update_empties_is_removed(library, tmp_path):
    """Going back from src/ to flat leaves src/ empty, and an empty folder is clutter."""
    new, old = _two_versions(library, tmp_path)
    project = tmp_path / "Proj"
    destination = project / "demo"

    installer.install_to(old, destination, project_root=project)
    assert (destination / "src" / "demo.c").is_file()

    installer.install_to(new, destination, project_root=project)

    assert (destination / "demo.c").is_file()
    assert (destination / "demo_config.h").is_file(), "the config did not come back up"
    assert not (destination / "src").exists()
