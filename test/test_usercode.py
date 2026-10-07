"""
Tests for USER CODE sections: what the user wrote between the markers survives
every install, everything else is the library's and is replaced.
"""

import json
import os

import pytest

from stm32_installer import cli, installer, manifest, usercode

CONFIG_V1 = (
    "/* demo_config.h, version 1 */\n"
    "/* USER CODE BEGIN DEMO_CONFIGURATION */\n"
    "#define DEMO_SIZE 8\n"
    "/* USER CODE END DEMO_CONFIGURATION */\n"
)

CONFIG_V2 = (
    "/* demo_config.h, version 2 */\n"
    "/* USER CODE BEGIN DEMO_CONFIGURATION */\n"
    "#define DEMO_SIZE 16\n"
    "/* USER CODE END DEMO_CONFIGURATION */\n"
    "/* USER CODE BEGIN DEMO_EXTRA */\n"
    "/* USER CODE END DEMO_EXTRA */\n"
)


# ----------------------------------------------------------------------------
# The markers themselves


def test_a_section_is_the_lines_between_its_markers():
    lines, sections = usercode.parse(CONFIG_V2.encode())

    first, last = sections["DEMO_CONFIGURATION"]
    assert lines[first:last] == [b"#define DEMO_SIZE 16\n"]
    assert sections["DEMO_EXTRA"][0] == sections["DEMO_EXTRA"][1], "an empty section has an empty body"


@pytest.mark.parametrize("text, says", [
    ("/* USER CODE BEGIN A */\n", "A has no END"),
    ("/* USER CODE END A */\n", "END A has no BEGIN"),
    ("/* USER CODE BEGIN A */\n/* USER CODE BEGIN B */\n", "B begins inside A"),
    ("/* USER CODE BEGIN A */\n/* USER CODE END B */\n", "END B closes A"),
    ("/* USER CODE BEGIN A */\n/* USER CODE END A */\n/* USER CODE BEGIN A */\n/* USER CODE END A */\n",
     "A is used twice"),
])
def test_markers_that_do_not_pair_are_named(text, says):
    with pytest.raises(usercode.MarkerError) as raised:
        usercode.parse(text.encode())

    assert says in str(raised.value)


@pytest.mark.parametrize("line", [
    "  /* USER CODE BEGIN Includes */",
    "/*USER CODE BEGIN Includes*/",
    "// USER CODE BEGIN Includes",
    "# USER CODE BEGIN Includes",
    "\t/* USER CODE BEGIN Includes */\r",
])
def test_a_marker_is_a_comment_alone_on_its_line(line):
    data = (line + "\nx\n/* USER CODE END Includes */\n").encode()

    assert list(usercode.parse(data)[1]) == ["Includes"]


@pytest.mark.parametrize("line", [
    "Keep it between `USER CODE BEGIN A` and `USER CODE END A`.",
    "/* Put it between USER CODE BEGIN A and the END line. */",
    "/* USER CODE BEGIN A */ int x;",
    "int x; /* USER CODE BEGIN A */",
])
def test_a_mention_is_not_a_marker(line):
    assert usercode.parse((line + "\n").encode())[1] == {}


def test_the_users_section_goes_into_the_new_file():
    old = CONFIG_V1.replace("DEMO_SIZE 8", "DEMO_SIZE 32").encode()

    merged = usercode.merge(CONFIG_V2.encode(), old)

    assert merged.data.decode() == CONFIG_V2.replace("DEMO_SIZE 16", "DEMO_SIZE 32")
    assert merged.kept == ["DEMO_CONFIGURATION"]
    assert merged.lost == [] and merged.broken is None


def test_an_empty_section_is_carried_but_not_reported_as_kept():
    """Nothing to tell the user about, and the report would only be noise."""
    old = CONFIG_V2.replace("DEMO_SIZE 16", "DEMO_SIZE 32").encode()

    merged = usercode.merge(CONFIG_V2.encode(), old)

    assert merged.kept == ["DEMO_CONFIGURATION"]


def test_a_section_only_the_new_version_has_starts_as_it_ships():
    new = CONFIG_V2.replace("BEGIN DEMO_EXTRA */\n", "BEGIN DEMO_EXTRA */\n#define DEMO_FAST 1\n")

    merged = usercode.merge(new.encode(), CONFIG_V1.encode())

    assert b"#define DEMO_FAST 1\n" in merged.data


def test_a_section_the_new_version_dropped_is_reported_when_it_held_something():
    old = CONFIG_V2.replace("BEGIN DEMO_EXTRA */\n", "BEGIN DEMO_EXTRA */\nmine();\n")

    assert usercode.merge(CONFIG_V1.encode(), old.encode()).lost == ["DEMO_EXTRA"]
    assert usercode.merge(CONFIG_V1.encode(), CONFIG_V2.encode()).lost == [], "an empty one is not a loss"


def test_an_old_copy_whose_markers_do_not_pair_gives_nothing_and_says_why():
    old = CONFIG_V1.replace("/* USER CODE END DEMO_CONFIGURATION */\n", "")

    merged = usercode.merge(CONFIG_V2.encode(), old.encode())

    assert merged.data == CONFIG_V2.encode()
    assert "DEMO_CONFIGURATION has no END" in merged.broken


def test_an_old_copy_with_no_markers_at_all_is_not_called_broken():
    merged = usercode.merge(CONFIG_V2.encode(), b"#define DEMO_SIZE 8\n")

    assert merged.broken is None
    assert merged.data == CONFIG_V2.encode()


def test_the_carried_lines_take_the_new_files_line_ending():
    old = CONFIG_V1.replace("DEMO_SIZE 8", "DEMO_SIZE 32").replace("\n", "\r\n").encode()

    merged = usercode.merge(CONFIG_V2.encode(), old)

    assert b"\r" not in merged.data, "one file mixing CRLF and LF"
    assert b"#define DEMO_SIZE 32\n" in merged.data


def test_the_fingerprint_ignores_the_sections_and_line_endings_only():
    base = usercode.fingerprint(CONFIG_V1.encode())

    assert usercode.fingerprint(CONFIG_V1.replace("DEMO_SIZE 8", "DEMO_SIZE 99").encode()) == base
    assert usercode.fingerprint(CONFIG_V1.replace("\n", "\r\n").encode()) == base
    assert usercode.fingerprint(CONFIG_V1.replace("version 1", "edited").encode()) != base


# ----------------------------------------------------------------------------
# Installing


def _version(library, tmp_path, label, config, header="/* header */\n", extra=None):
    """A version of demo whose config is an ordinary header carrying USER CODE sections."""
    files = {"inc/demo_config.h": config, "inc/demo.h": header}
    files.update(extra or {})
    root = library(
        root=tmp_path / label / "demo",
        headers=("inc/demo.h", "inc/demo_config.h") + tuple(extra or ()),
        once=[],
        extra_files=files,
    )

    return manifest.load(root)


def _install(lib, tmp_path):
    project = tmp_path / "Proj"
    destination = project / "demo"

    return installer.install_to(lib, destination, project_root=project), destination


def test_an_update_keeps_the_users_setting_and_takes_the_rest(library, tmp_path):
    v1 = _version(library, tmp_path, "v1", CONFIG_V1)
    v2 = _version(library, tmp_path, "v2", CONFIG_V2)

    _, destination = _install(v1, tmp_path)
    config = destination / "demo_config.h"
    config.write_text(CONFIG_V1.replace("DEMO_SIZE 8", "DEMO_SIZE 32"), encoding="utf-8")

    result, _ = _install(v2, tmp_path)

    assert config.read_text(encoding="utf-8") == CONFIG_V2.replace("DEMO_SIZE 16", "DEMO_SIZE 32")
    assert result.preserved == [(config, ["DEMO_CONFIGURATION"])]
    assert result.backups == [], "a backup for a change made where changes belong"
    assert result.was_update


def test_a_hand_edit_outside_the_sections_is_saved_before_it_is_replaced(library, tmp_path):
    v1 = _version(library, tmp_path, "v1", CONFIG_V1)

    _, destination = _install(v1, tmp_path)
    header = destination / "demo.h"
    header.write_text("/* header, fixed by hand */\n", encoding="utf-8")

    result, _ = _install(v1, tmp_path)

    assert header.read_text(encoding="utf-8") == "/* header */\n", "the library was not put right"
    [(path, saved, reason)] = result.backups
    assert path == header
    assert saved.read_text(encoding="utf-8") == "/* header, fixed by hand */\n"
    assert "changed outside" in reason


def test_a_file_nobody_touched_is_neither_saved_nor_rewritten(library, tmp_path):
    v1 = _version(library, tmp_path, "v1", CONFIG_V1)

    _, destination = _install(v1, tmp_path)
    header = destination / "demo.h"
    os.utime(header, (1_000_000, 1_000_000))

    result, _ = _install(v1, tmp_path)

    assert result.backups == []
    assert header.stat().st_mtime == 1_000_000, "an identical file was written again"
    assert list(destination.glob("*.bak")) == []


def test_a_section_the_new_version_lost_is_saved_first(library, tmp_path):
    v2 = _version(library, tmp_path, "v2", CONFIG_V2)
    v1 = _version(library, tmp_path, "v1", CONFIG_V1)

    _, destination = _install(v2, tmp_path)
    config = destination / "demo_config.h"
    mine = CONFIG_V2.replace("BEGIN DEMO_EXTRA */\n", "BEGIN DEMO_EXTRA */\nmine();\n")
    config.write_text(mine, encoding="utf-8")

    result, _ = _install(v1, tmp_path)

    [(_, saved, reason)] = result.backups
    assert "DEMO_EXTRA" in reason
    assert "mine();" in saved.read_text(encoding="utf-8")
    assert "mine();" not in config.read_text(encoding="utf-8")


def test_broken_markers_in_the_copy_are_replaced_and_saved(library, tmp_path):
    v1 = _version(library, tmp_path, "v1", CONFIG_V1)

    _, destination = _install(v1, tmp_path)
    config = destination / "demo_config.h"
    config.write_text(CONFIG_V1.replace("/* USER CODE END DEMO_CONFIGURATION */\n", ""), encoding="utf-8")

    result, _ = _install(v1, tmp_path)

    assert config.read_text(encoding="utf-8") == CONFIG_V1, "the file was not put right"
    [(_, _, reason)] = result.backups
    assert "do not pair" in reason


def test_a_library_with_broken_markers_installs_nothing(library, tmp_path):
    v1 = _version(library, tmp_path, "v1", CONFIG_V1)
    _, destination = _install(v1, tmp_path)
    (destination / "demo.h").write_text("/* mine */\n", encoding="utf-8")

    bad = _version(library, tmp_path, "bad", CONFIG_V1, header="/* USER CODE BEGIN X */\n")

    with pytest.raises(installer.InstallError) as raised:
        _install(bad, tmp_path)

    assert "do not pair" in str(raised.value)
    assert (destination / "demo.h").read_text(encoding="utf-8") == "/* mine */\n", "half installed"


def test_a_removed_file_that_held_the_users_work_is_saved_first(library, tmp_path):
    extra = {"inc/demo_port.h": "/* USER CODE BEGIN PORT */\n/* USER CODE END PORT */\n"}
    v1 = _version(library, tmp_path, "v1", CONFIG_V1, extra=extra)
    v2 = _version(library, tmp_path, "v2", CONFIG_V1)

    _, destination = _install(v1, tmp_path)
    port = destination / "demo_port.h"
    port.write_text("/* USER CODE BEGIN PORT */\nmy_port();\n/* USER CODE END PORT */\n", encoding="utf-8")

    result, _ = _install(v2, tmp_path)

    assert not port.exists(), "a stale copy left to be compiled"
    [(_, saved, reason)] = result.backups
    assert "my_port();" in saved.read_text(encoding="utf-8")
    assert "no longer part of the library" in reason


def test_a_config_that_was_once_the_users_keeps_its_section_and_is_saved_when_it_differs(library, tmp_path):
    """The step a library takes when it drops once: its config becomes an ordinary file."""
    old_root = library(root=tmp_path / "old" / "demo", once=[{"from": "template/demo_config.h"}],
                       extra_files={"template/demo_config.h": CONFIG_V1})
    _, destination = _install(manifest.load(old_root), tmp_path)
    config = destination / "demo_config.h"
    config.write_text(CONFIG_V1.replace("DEMO_SIZE 8", "DEMO_SIZE 32") + "#define MINE 1\n", encoding="utf-8")

    result, _ = _install(_version(library, tmp_path, "v2", CONFIG_V2), tmp_path)

    assert "#define DEMO_SIZE 32" in config.read_text(encoding="utf-8")
    [(_, saved, reason)] = result.backups
    assert "#define MINE 1" in saved.read_text(encoding="utf-8")
    assert "yours to edit until now" in reason


def test_without_a_fingerprint_in_the_record_code_is_replaced_as_before(library, tmp_path):
    """A project last installed by 1.6.0 has no fingerprints. Code was always replaced then too."""
    v1 = _version(library, tmp_path, "v1", CONFIG_V1)
    _, destination = _install(v1, tmp_path)

    record_path = tmp_path / "Proj" / installer.RECORD_NAME
    record = json.loads(record_path.read_text(encoding="utf-8"))
    del record["libraries"]["demo"]["fingerprints"]
    record_path.write_text(json.dumps(record), encoding="utf-8")
    (destination / "demo.h").write_text("/* edited */\n", encoding="utf-8")

    result, _ = _install(v1, tmp_path)

    assert result.backups == []
    assert (destination / "demo.h").read_text(encoding="utf-8") == "/* header */\n"


def test_the_record_keeps_a_fingerprint_of_every_file_written(library, tmp_path):
    _install(_version(library, tmp_path, "v1", CONFIG_V1), tmp_path)

    record = installer.installed_libraries(tmp_path / "Proj")["demo"]

    assert set(record["fingerprints"]) == {"demo/demo.h", "demo/demo_config.h", "demo/demo.c"}
    assert record["fingerprints"]["demo/demo_config.h"] == usercode.fingerprint(CONFIG_V1.encode())


def test_a_readme_that_shows_the_markers_installs_and_is_copied_as_it_is(library, tmp_path):
    """A README can show one example twice, or mention a marker in a sentence."""
    example = "```c\n/* USER CODE BEGIN DEMO_CONFIGURATION */\n#define DEMO_SIZE 8\n/* USER CODE END DEMO_CONFIGURATION */\n```\n"
    readme = "Keep it between `USER CODE BEGIN DEMO_CONFIGURATION` and its END.\n" + example + example
    root = library(root=tmp_path / "v1" / "demo", extra_files={"README.md": readme})
    data = (root / "installer.yml").read_text(encoding="utf-8") + "extras:\n  - README.md\n"
    (root / "installer.yml").write_text(data, encoding="utf-8")

    _, destination = _install(manifest.load(root), tmp_path)
    (destination / "README.md").write_text("my notes\n", encoding="utf-8")
    result, _ = _install(manifest.load(root), tmp_path)

    assert (destination / "README.md").read_text(encoding="utf-8") == readme
    assert result.backups == [] and result.preserved == []


def test_once_still_means_copied_once(library, tmp_path):
    """Libraries already released list once, and must keep working."""
    root = library(root=tmp_path / "v1" / "demo")
    _, destination = _install(manifest.load(root), tmp_path)
    config = destination / "demo_config.h"
    config.write_text("#define DEMO_SIZE 99\n", encoding="utf-8")

    result, _ = _install(manifest.load(root), tmp_path)

    assert config.read_text(encoding="utf-8") == "#define DEMO_SIZE 99\n"
    assert result.backups == []


def test_the_report_says_what_was_kept_and_what_was_saved(library, project, tmp_path, capsys):
    root = project(cmake=True)
    v1 = _version(library, tmp_path, "v1", CONFIG_V1).root

    assert cli.main([str(v1), "--project", str(root), "--dir", "demo"]) == 0
    (root / "demo" / "demo_config.h").write_text(CONFIG_V1.replace("DEMO_SIZE 8", "DEMO_SIZE 32"),
                                                 encoding="utf-8")
    (root / "demo" / "demo.h").write_text("/* edited */\n", encoding="utf-8")
    capsys.readouterr()

    assert cli.main([str(v1), "--project", str(root), "--dir", "demo"]) == 0
    out = capsys.readouterr().out

    assert "your USER CODE DEMO_CONFIGURATION" in out
    assert "saved" in out and "demo.h." in out and "changed outside" in out
    assert "This was an update" in out
