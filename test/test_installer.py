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
    assert len(result.config_created) == 1


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
    assert result.config_kept
    assert not result.config_created
    assert result.was_update


def test_code_is_replaced_on_a_second_install(library, tmp_path):
    """Updating has to actually update, or there is no point to it."""
    lib = manifest.load(library())
    destination = tmp_path / "Proj" / "demo"

    installer.install_to(lib, destination)
    (destination / "demo.c").write_text("/* stale */\n", encoding="utf-8")

    installer.install_to(lib, destination)

    assert (destination / "demo.c").read_text(encoding="utf-8") == "/* demo.c */\n"


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
    assert not (root / "library.yml").exists()
    assert "test" in result.removed


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
