"""
Tests for a library file that a new version puts in another folder.

littlefs went from littlefs/lfs_defines.h to littlefs/src/lfs_defines.h. The
user's settings live in its USER CODE section, and before 1.9.0 an update left
them behind in a .bak and gave the new file the defaults. They go with the
file now, found by its name among the files the last install wrote.
"""

from stm32_installer import cli, installer, manifest

CONFIG = (
    "#ifndef DEMO_CONFIG_H\n"
    "/* USER CODE BEGIN DEMO_CONFIGURATION */\n"
    "#define DEMO_SIZE 8\n"
    "/* USER CODE END DEMO_CONFIGURATION */\n"
    "#endif\n"
)


def _version(library, tmp_path, name, config_at):
    """A library whose demo_config.h lands at config_at."""
    return manifest.load(library(
        root=tmp_path / name,
        headers=["demo.h", {"from": "demo_config.h", "to": config_at}],
        sources=["demo.c"],
        once=[],
        extra_files={"demo_config.h": CONFIG},
    ))


def _install_then_edit(library, tmp_path, outside=False):
    """The first version installed, and the user's setting changed in it."""
    root = tmp_path / "Proj"
    installer.install_to(_version(library, tmp_path, "v1", "demo_config.h"), root / "demo", project_root=root)

    path = root / "demo" / "demo_config.h"
    text = path.read_text(encoding="utf-8").replace("DEMO_SIZE 8", "DEMO_SIZE 32")

    if outside:
        text = text.replace("#endif", "#endif /* mine */")

    path.write_text(text, encoding="utf-8")

    return root


def test_a_moved_file_takes_its_sections_with_it(library, tmp_path):
    root = _install_then_edit(library, tmp_path)

    result = installer.install_to(_version(library, tmp_path, "v2", "src/demo_config.h"), root / "demo",
                                  project_root=root)
    moved = root / "demo" / "src" / "demo_config.h"

    assert "#define DEMO_SIZE 32" in moved.read_text(encoding="utf-8")
    assert not (root / "demo" / "demo_config.h").exists()
    assert result.backups == [], "a .bak for a setting that was carried"
    assert [(old.name, new, kept) for old, new, kept in result.carried] == \
        [("demo_config.h", moved, ["DEMO_CONFIGURATION"])]


def test_a_hand_edit_outside_the_sections_is_saved_once(library, tmp_path):
    """The section still moves. What was outside it is in one .bak, not two."""
    root = _install_then_edit(library, tmp_path, outside=True)

    result = installer.install_to(_version(library, tmp_path, "v2", "src/demo_config.h"), root / "demo",
                                  project_root=root)

    assert "#define DEMO_SIZE 32" in (root / "demo" / "src" / "demo_config.h").read_text(encoding="utf-8")
    assert len(result.backups) == 1
    assert "outside its USER CODE sections" in result.backups[0][2]
    assert "/* mine */" in result.backups[0][1].read_text(encoding="utf-8")


def test_two_old_copies_of_one_name_are_not_a_move(library, tmp_path):
    """Which one would it be? Neither is guessed at, and both are kept aside as before."""
    root = tmp_path / "Proj"
    first = manifest.load(library(
        root=tmp_path / "v1",
        headers=["demo.h", "a/demo_config.h", "b/demo_config.h"],
        sources=["demo.c"],
        once=[],
        install={"layout": "mirror"},
        extra_files={"a/demo_config.h": CONFIG, "b/demo_config.h": CONFIG},
    ))
    installer.install_to(first, root / "demo", project_root=root)

    for folder in ("a", "b"):
        path = root / "demo" / folder / "demo_config.h"
        path.write_text(path.read_text(encoding="utf-8").replace("DEMO_SIZE 8", "DEMO_SIZE 32"), encoding="utf-8")

    result = installer.install_to(_version(library, tmp_path, "v2", "src/demo_config.h"), root / "demo",
                                  project_root=root)

    assert "#define DEMO_SIZE 8" in (root / "demo" / "src" / "demo_config.h").read_text(encoding="utf-8")
    assert result.carried == []
    assert len(result.backups) == 2


def test_a_file_still_installed_where_it_was_is_not_a_move(library, tmp_path):
    """The old place is still the library's, so its sections stay there."""
    root = _install_then_edit(library, tmp_path)
    second = manifest.load(library(
        root=tmp_path / "v2",
        headers=["demo.h", "demo_config.h", {"from": "demo_config.h", "to": "src/demo_config.h"}],
        sources=["demo.c"],
        once=[],
        extra_files={"demo_config.h": CONFIG},
    ))

    result = installer.install_to(second, root / "demo", project_root=root)

    assert "#define DEMO_SIZE 32" in (root / "demo" / "demo_config.h").read_text(encoding="utf-8")
    assert "#define DEMO_SIZE 8" in (root / "demo" / "src" / "demo_config.h").read_text(encoding="utf-8")
    assert result.carried == []


def test_a_first_install_moves_nothing(library, tmp_path):
    root = tmp_path / "Proj"

    result = installer.install_to(_version(library, tmp_path, "v2", "src/demo_config.h"), root / "demo",
                                  project_root=root)

    assert result.carried == []


def test_the_report_says_the_setting_went_with_the_file(library, project, tmp_path, capsys):
    root = project(cmake=True)
    first = library(root=tmp_path / "v1", headers=["demo.h", "demo_config.h"], sources=["demo.c"], once=[],
                    extra_files={"demo_config.h": CONFIG})
    second = library(root=tmp_path / "v2", headers=["demo.h", {"from": "demo_config.h", "to": "src/demo_config.h"}],
                     sources=["demo.c"], once=[], extra_files={"demo_config.h": CONFIG})

    assert cli.main([str(first), "--project", str(root), "--dir", "demo"]) == 0
    path = root / "demo" / "demo_config.h"
    path.write_text(path.read_text(encoding="utf-8").replace("DEMO_SIZE 8", "DEMO_SIZE 32"), encoding="utf-8")
    capsys.readouterr()

    assert cli.main([str(second), "--project", str(root), "--dir", "demo"]) == 0
    out = capsys.readouterr().out

    assert "demo/demo_config.h -> demo/src/demo_config.h" in out
    assert "DEMO_CONFIGURATION went with it" in out
    assert "saved" not in out
    assert "removed demo/demo_config.h" not in out.replace("  ", " ")
