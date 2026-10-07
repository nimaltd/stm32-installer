"""
Tests for install.defines: defines a library needs the whole project built with.

littlefs is the reason they exist. It reads its settings from a header named by
LFS_DEFINES, and only when the compiler is given -DLFS_DEFINES=lfs_defines.h.
The define has to reach every file that includes lfs.h, not only lfs.c, since
LFS_THREADSAFE adds two members to struct lfs_config: two files that disagree
about it disagree about where every later member sits, and nothing reports it.
So each IDE gets the define where USE_HAL_DRIVER already is, for the whole
project, in every configuration.
"""

import json
import re

import pytest

from stm32_installer import cli, download, ide, installer, manifest
from stm32_installer.ide import base, cmake, cubeide, iar, keil, makefile

LFS = "LFS_DEFINES=lfs_defines.h"


def _install(library_factory, project_root, defines=(LFS,), root=None):
    """A library asking for these defines, and the folder it is installed into."""
    lib = manifest.load(library_factory(install={"defines": list(defines)}, root=root))
    destination = project_root / "demo"
    destination.mkdir(parents=True, exist_ok=True)

    return lib, destination


@pytest.fixture
def no_network(monkeypatch):
    """Fail loudly if anything tries to reach GitHub."""

    def refuse(*args, **kwargs):
        raise AssertionError("went online for something that was on disk")

    monkeypatch.setattr(download, "fetch", refuse)


# ----------------------------------------------------------------------------
# The manifest.
# ----------------------------------------------------------------------------


def test_the_manifest_reads_the_defines(library):
    lib = manifest.load(library(install={"defines": [LFS, "DEMO_FAST"]}))

    assert lib.defines == [LFS, "DEMO_FAST"]


def test_a_library_without_defines_has_none(library):
    assert manifest.load(library()).defines == []


@pytest.mark.parametrize("bad", [
    "LFS_DEFINES=lfs defines.h",          # a space would carry a second flag in
    'LFS_DEFINES="lfs_defines.h"',        # a quote breaks the XML and the Makefile
    "LFS_DEFINES=a.h -include evil.h",
    "1LFS=1",                             # not a C name
    "LFS_DEFINES=<x>",
    "LFS_DEFINES=",
    "-DLFS_DEFINES=lfs_defines.h",        # the flag, not the define
])
def test_a_define_that_is_not_plain_is_refused(bad, library):
    with pytest.raises(manifest.ManifestError, match="install.defines"):
        manifest.load(library(install={"defines": [bad]}))


def test_one_name_set_twice_is_refused(library):
    with pytest.raises(manifest.ManifestError, match="LFS_DEFINES"):
        manifest.load(library(install={"defines": [LFS, "LFS_DEFINES=other.h"]}))


def test_defines_written_as_one_line_are_refused(library):
    """A string would be read one character at a time, each a valid define."""
    with pytest.raises(manifest.ManifestError, match="list"):
        manifest.load(library(install={"defines": "LFS"}))


# ----------------------------------------------------------------------------
# What to do to one list.
# ----------------------------------------------------------------------------


def test_the_plan_adds_what_is_missing_and_keeps_the_rest():
    remove, add, clashes = base.plan_defines(["USE_HAL_DRIVER", "STM32G431xx"], [LFS], [])

    assert (remove, add, clashes) == ([], [LFS], [])


def test_the_plan_leaves_a_list_that_already_has_it():
    assert base.plan_defines(["USE_HAL_DRIVER", LFS], [LFS], []) == ([], [], [])


def test_the_plan_replaces_a_value_the_library_put_there():
    remove, add, clashes = base.plan_defines(["USE_HAL_DRIVER", "LFS_DEFINES=old.h"], [LFS], ["LFS_DEFINES=old.h"])

    assert (remove, add, clashes) == (["LFS_DEFINES=old.h"], [LFS], [])


def test_the_plan_never_replaces_a_value_of_the_users():
    """Not in dropped means this library did not put it there."""
    remove, add, clashes = base.plan_defines(["LFS_DEFINES=mine.h"], [LFS], [])

    assert (remove, add, clashes) == ([], [], [(LFS, "LFS_DEFINES=mine.h")])


def test_the_plan_removes_only_what_was_dropped():
    remove, add, _ = base.plan_defines(["USE_HAL_DRIVER", "OLD_ONE"], [], ["OLD_ONE", "NOT_THERE"])

    assert (remove, add) == (["OLD_ONE"], [])


# ----------------------------------------------------------------------------
# CMake.
# ----------------------------------------------------------------------------


def test_cmake_hands_the_define_to_the_whole_project(library, project):
    """INTERFACE, so it reaches every file of the application, not only lfs.c."""
    root = project(cmake=True)
    lib, destination = _install(library, root)

    cmake.integrate(root / "CMakeLists.txt", lib, destination, root)
    text = (destination / "CMakeLists.txt").read_text(encoding="utf-8")

    assert f"target_compile_definitions(demo_lib INTERFACE\n    {LFS}\n)\n" in text


def test_cmake_writes_nothing_new_for_a_library_without_defines(library, project):
    """Every project installed before this must not see its file rewritten."""
    root = project(cmake=True)
    lib, destination = _install(library, root, defines=())

    cmake.integrate(root / "CMakeLists.txt", lib, destination, root)
    text = (destination / "CMakeLists.txt").read_text(encoding="utf-8")

    assert "target_compile_definitions" not in text
    assert text.endswith("target_include_directories(demo_lib INTERFACE ${CMAKE_CURRENT_SOURCE_DIR})\n")


# ----------------------------------------------------------------------------
# STM32CubeIDE.
# ----------------------------------------------------------------------------


def _values(option_body):
    return re.findall(r'value="([^"]*)"', option_body)


def _cubeide_lists(text):
    """The define values of each C compiler list, in file order."""
    return [_values(m.group(2)) for m in cubeide.DEFINE_OPTION.finditer(text)]


def test_cubeide_adds_the_define_to_every_configuration(library, project):
    root = project(cubeide=True)
    lib, destination = _install(library, root)

    outcome = cubeide.integrate(root / ".cproject", lib, destination, root)
    text = (root / ".cproject").read_text(encoding="utf-8")

    assert outcome.status == ide.CHANGED
    assert "defines" in outcome.message
    assert _cubeide_lists(text) == [
        ["DEBUG", "USE_HAL_DRIVER", "STM32G431xx", LFS],
        ["USE_HAL_DRIVER", "STM32G431xx", LFS],
    ]


def test_cubeide_leaves_the_assembler_alone(library, project):
    root = project(cubeide=True)
    lib, destination = _install(library, root)

    cubeide.integrate(root / ".cproject", lib, destination, root)
    text = (root / ".cproject").read_text(encoding="utf-8")
    assembler = re.search(r'assembler\.option\.definedsymbols"[^>]*>(.*?)</option>', text, re.DOTALL)

    assert _values(assembler.group(1)) == ["DEBUG"]


def test_cubeide_lines_the_define_up_with_the_ones_there(library, project):
    root = project(cubeide=True)
    lib, destination = _install(library, root)

    cubeide.integrate(root / ".cproject", lib, destination, root)
    text = (root / ".cproject").read_text(encoding="utf-8")

    assert (
        '\t\t\t\t\t\t<listOptionValue builtIn="false" value="STM32G431xx"/>\n'
        f'\t\t\t\t\t\t<listOptionValue builtIn="false" value="{LFS}"/>\n'
        "\t\t\t\t\t</option>\n"
    ) in text


def test_cubeide_does_not_add_the_define_twice(library, project):
    root = project(cubeide=True)
    lib, destination = _install(library, root)

    cubeide.integrate(root / ".cproject", lib, destination, root)
    second = cubeide.integrate(root / ".cproject", lib, destination, root)

    assert second.status == ide.ALREADY
    assert (root / ".cproject").read_text(encoding="utf-8").count(LFS) == 2


def test_cubeide_follows_a_value_the_library_changed(library, project):
    root = project(cubeide=True)
    lib, destination = _install(library, root, defines=["LFS_DEFINES=old.h"])
    cubeide.integrate(root / ".cproject", lib, destination, root)

    lib, _ = _install(library, root, root=root.parent / "v2")
    cubeide.integrate(root / ".cproject", lib, destination, root, dropped_defines=["LFS_DEFINES=old.h"])
    text = (root / ".cproject").read_text(encoding="utf-8")

    assert "old.h" not in text
    assert _cubeide_lists(text)[1] == ["USE_HAL_DRIVER", "STM32G431xx", LFS]


def test_cubeide_takes_out_a_define_the_library_no_longer_has(library, project):
    root = project(cubeide=True)
    lib, destination = _install(library, root)
    cubeide.integrate(root / ".cproject", lib, destination, root)

    lib, _ = _install(library, root, defines=(), root=root.parent / "v2")
    cubeide.integrate(root / ".cproject", lib, destination, root, dropped_defines=[LFS])
    text = (root / ".cproject").read_text(encoding="utf-8")

    assert LFS not in text
    assert _cubeide_lists(text)[1] == ["USE_HAL_DRIVER", "STM32G431xx"]


def test_cubeide_keeps_a_value_the_user_set_and_says_so(library, project):
    root = project(cubeide=True)
    path = root / ".cproject"
    path.write_text(path.read_text(encoding="utf-8").replace('value="STM32G431xx"', 'value="LFS_DEFINES=mine.h"'),
                    encoding="utf-8")
    lib, destination = _install(library, root)

    outcome = cubeide.integrate(path, lib, destination, root)
    text = path.read_text(encoding="utf-8")

    assert LFS not in text
    assert text.count("LFS_DEFINES=mine.h") == 2
    assert any("LFS_DEFINES=mine.h" in step and "left as it is" in step for step in outcome.steps)


def test_cubeide_without_a_define_list_says_what_to_add(library, project):
    root = project(cubeide=True)
    path = root / ".cproject"
    path.write_text(re.sub(r"[ \t]*<option id=\"d[ab]\".*?</option>\n", "",
                           path.read_text(encoding="utf-8"), flags=re.DOTALL), encoding="utf-8")
    lib, destination = _install(library, root)

    outcome = cubeide.integrate(path, lib, destination, root)

    assert outcome.status == ide.MANUAL
    assert any(LFS in step for step in outcome.steps)
    assert 'value="../demo"' in path.read_text(encoding="utf-8"), "the rest was not done"


# ----------------------------------------------------------------------------
# Keil.
# ----------------------------------------------------------------------------


def _keil_defines(text):
    return re.findall(r"<Define>(.*?)</Define>", text)


def test_keil_adds_the_define_to_the_c_compiler_only(library, project):
    """The <Define> under <Aads> is the assembler's."""
    root = project(keil=True)
    path = root / "MDK" / "Proj.uvprojx"
    lib, destination = _install(library, root)

    outcome = keil.integrate(path, lib, destination, root)

    assert outcome.status == ide.CHANGED
    assert _keil_defines(path.read_text(encoding="utf-8")) == [f"USE_HAL_DRIVER,STM32G431xx,{LFS}", ""]


def test_keil_adds_the_define_to_every_target(library, project):
    root = project(keil=True)
    path = root / "MDK" / "Proj.uvprojx"
    text = path.read_text(encoding="utf-8")
    target = re.search(r"    <Target>.*?</Target>\n", text, re.DOTALL).group(0)
    path.write_text(text.replace(target, target + target), encoding="utf-8")
    lib, destination = _install(library, root)

    keil.integrate(path, lib, destination, root)

    assert _keil_defines(path.read_text(encoding="utf-8")) == [f"USE_HAL_DRIVER,STM32G431xx,{LFS}", ""] * 2


@pytest.mark.parametrize("written, expected", [
    ("USE_HAL_DRIVER STM32G431xx", f"USE_HAL_DRIVER STM32G431xx {LFS}"),
    ("USE_HAL_DRIVER, STM32G431xx", f"USE_HAL_DRIVER, STM32G431xx, {LFS}"),
    ("USE_HAL_DRIVER", f"USE_HAL_DRIVER,{LFS}"),
    ("", LFS),
])
def test_keil_follows_the_separator_already_used(written, expected, library, project):
    root = project(keil=True)
    path = root / "MDK" / "Proj.uvprojx"
    path.write_text(path.read_text(encoding="utf-8").replace("USE_HAL_DRIVER,STM32G431xx", written),
                    encoding="utf-8")
    lib, destination = _install(library, root)

    keil.integrate(path, lib, destination, root)

    assert _keil_defines(path.read_text(encoding="utf-8"))[0] == expected


def test_keil_follows_a_value_the_library_changed(library, project):
    root = project(keil=True)
    path = root / "MDK" / "Proj.uvprojx"
    lib, destination = _install(library, root, defines=["LFS_DEFINES=old.h"])
    keil.integrate(path, lib, destination, root)

    lib, _ = _install(library, root, root=root.parent / "v2")
    keil.integrate(path, lib, destination, root, dropped_defines=["LFS_DEFINES=old.h"])

    assert _keil_defines(path.read_text(encoding="utf-8"))[0] == f"USE_HAL_DRIVER,STM32G431xx,{LFS}"


def test_keil_keeps_a_value_the_user_set(library, project):
    root = project(keil=True)
    path = root / "MDK" / "Proj.uvprojx"
    path.write_text(path.read_text(encoding="utf-8").replace("STM32G431xx", "LFS_DEFINES=mine.h"), encoding="utf-8")
    lib, destination = _install(library, root)

    outcome = keil.integrate(path, lib, destination, root)

    assert _keil_defines(path.read_text(encoding="utf-8"))[0] == "USE_HAL_DRIVER,LFS_DEFINES=mine.h"
    assert any("left as it is" in step for step in outcome.steps)


def test_keil_does_not_add_the_define_twice(library, project):
    root = project(keil=True)
    path = root / "MDK" / "Proj.uvprojx"
    lib, destination = _install(library, root)

    keil.integrate(path, lib, destination, root)
    second = keil.integrate(path, lib, destination, root)

    assert second.status == ide.ALREADY


def test_keil_without_a_define_list_says_what_to_add(library, project):
    root = project(keil=True)
    path = root / "MDK" / "Proj.uvprojx"
    path.write_text(re.sub(r"[ \t]*<Define>[^<]*</Define>\n", "", path.read_text(encoding="utf-8")), encoding="utf-8")
    lib, destination = _install(library, root)

    outcome = keil.integrate(path, lib, destination, root)

    assert outcome.status == ide.MANUAL
    assert any(LFS in step for step in outcome.steps)


# ----------------------------------------------------------------------------
# IAR.
# ----------------------------------------------------------------------------


def _iar_defines(text):
    body = iar.DEFINE_OPTION.search(text).group(2)

    return re.findall(r"<state>([^<]*)</state>", body)


def test_iar_adds_the_define_in_line_with_the_others(library, project):
    root = project(iar=True)
    path = root / "EWARM" / "Proj.ewp"
    lib, destination = _install(library, root)

    outcome = iar.integrate(path, lib, destination, root)
    text = path.read_text(encoding="utf-8")

    assert outcome.status == ide.CHANGED
    assert (
        "                    <state>STM32G431xx</state>\n"
        f"                    <state>{LFS}</state>\n"
        "                </option>\n"
    ) in text
    assert LFS not in (root / "EWARM" / "Proj.ewt").read_text(encoding="utf-8")


def test_iar_does_not_add_the_define_twice(library, project):
    root = project(iar=True)
    path = root / "EWARM" / "Proj.ewp"
    lib, destination = _install(library, root)

    iar.integrate(path, lib, destination, root)
    second = iar.integrate(path, lib, destination, root)

    assert second.status == ide.ALREADY
    assert _iar_defines(path.read_text(encoding="utf-8")) == ["USE_HAL_DRIVER", "STM32G431xx", LFS]


def test_iar_follows_a_value_the_library_changed(library, project):
    root = project(iar=True)
    path = root / "EWARM" / "Proj.ewp"
    lib, destination = _install(library, root, defines=["LFS_DEFINES=old.h"])
    iar.integrate(path, lib, destination, root)

    lib, _ = _install(library, root, root=root.parent / "v2")
    iar.integrate(path, lib, destination, root, dropped_defines=["LFS_DEFINES=old.h"])
    text = path.read_text(encoding="utf-8")

    assert _iar_defines(text) == ["USE_HAL_DRIVER", "STM32G431xx", LFS]
    assert "old.h" not in text


def test_iar_keeps_a_value_the_user_set(library, project):
    root = project(iar=True)
    path = root / "EWARM" / "Proj.ewp"
    path.write_text(path.read_text(encoding="utf-8").replace("<state>STM32G431xx", "<state>LFS_DEFINES=mine.h"),
                    encoding="utf-8")
    lib, destination = _install(library, root)

    outcome = iar.integrate(path, lib, destination, root)

    assert _iar_defines(path.read_text(encoding="utf-8")) == ["USE_HAL_DRIVER", "LFS_DEFINES=mine.h"]
    assert any("left as it is" in step for step in outcome.steps)


def test_iar_without_a_define_list_says_what_to_add(library, project):
    root = project(iar=True)
    path = root / "EWARM" / "Proj.ewp"
    path.write_text(re.sub(r"[ \t]*<option>\s*<name>CCDefines</name>.*?</option>\n", "",
                           path.read_text(encoding="utf-8"), flags=re.DOTALL), encoding="utf-8")
    lib, destination = _install(library, root)

    outcome = iar.integrate(path, lib, destination, root)

    assert outcome.status == ide.MANUAL
    assert any(LFS in step for step in outcome.steps)


# ----------------------------------------------------------------------------
# A CubeMX Makefile.
# ----------------------------------------------------------------------------


def test_the_makefile_gets_the_define_in_c_defs(library, project):
    root = project(makefile=True)
    lib, destination = _install(library, root)

    outcome = makefile.integrate(root / "Makefile", lib, destination, root)
    text = (root / "Makefile").read_text(encoding="utf-8")

    assert outcome.status == ide.CHANGED
    assert "C_DEFS" in outcome.message
    assert f"C_DEFS =  \\\n-DUSE_HAL_DRIVER \\\n-DSTM32G431xx \\\n-D{LFS}\n\n# C includes\n" in text


def test_the_makefile_does_not_get_the_define_twice(library, project):
    root = project(makefile=True)
    lib, destination = _install(library, root)

    makefile.integrate(root / "Makefile", lib, destination, root)
    second = makefile.integrate(root / "Makefile", lib, destination, root)

    assert second.status == ide.ALREADY


def test_the_makefile_list_stays_whole_when_the_library_takes_its_define_back(library, project):
    root = project(makefile=True)
    lib, destination = _install(library, root)
    makefile.integrate(root / "Makefile", lib, destination, root)

    lib, _ = _install(library, root, defines=(), root=root.parent / "v2")
    makefile.integrate(root / "Makefile", lib, destination, root, dropped_defines=[LFS])
    text = (root / "Makefile").read_text(encoding="utf-8")

    assert "C_DEFS =  \\\n-DUSE_HAL_DRIVER \\\n-DSTM32G431xx\n\n# C includes\n" in text


def test_the_makefile_follows_a_value_the_library_changed(library, project):
    root = project(makefile=True)
    lib, destination = _install(library, root, defines=["LFS_DEFINES=old.h", "DEMO_FAST"])
    makefile.integrate(root / "Makefile", lib, destination, root)

    lib, _ = _install(library, root, defines=[LFS, "DEMO_FAST"], root=root.parent / "v2")
    makefile.integrate(root / "Makefile", lib, destination, root, dropped_defines=["LFS_DEFINES=old.h"])
    text = (root / "Makefile").read_text(encoding="utf-8")

    assert f"-DSTM32G431xx \\\n-DDEMO_FAST \\\n-D{LFS}\n\n" in text


def test_the_makefile_keeps_a_value_the_user_set(library, project):
    root = project(makefile=True)
    path = root / "Makefile"
    path.write_text(path.read_text(encoding="utf-8").replace("-DSTM32G431xx", "-DLFS_DEFINES=mine.h"),
                    encoding="utf-8")
    lib, destination = _install(library, root)

    outcome = makefile.integrate(path, lib, destination, root)

    assert f"-D{LFS}" not in path.read_text(encoding="utf-8")
    assert any("left as it is" in step for step in outcome.steps)


def test_a_makefile_without_c_defs_says_what_to_add(library, project):
    root = project(makefile=True)
    path = root / "Makefile"
    path.write_text(path.read_text(encoding="utf-8").replace("C_DEFS =  \\\n-DUSE_HAL_DRIVER \\\n-DSTM32G431xx\n", ""),
                    encoding="utf-8")
    lib, destination = _install(library, root)

    outcome = makefile.integrate(path, lib, destination, root)

    assert outcome.status == ide.MANUAL
    assert any(f"-D{LFS}" in step for step in outcome.steps)


# ----------------------------------------------------------------------------
# Line endings, for every backend.
# ----------------------------------------------------------------------------

BACKENDS = [
    ("cubeide", ".cproject", dict(cubeide=True)),
    ("keil", "MDK/Proj.uvprojx", dict(keil=True)),
    ("iar", "EWARM/Proj.ewp", dict(iar=True)),
    ("makefile", "Makefile", dict(makefile=True)),
]


@pytest.mark.parametrize("backend, where, options", BACKENDS)
def test_a_crlf_project_stays_crlf_with_a_define(backend, where, options, library, project):
    root = project(newline="\r\n", **options)
    path = root / where
    lib, destination = _install(library, root)

    getattr(ide, backend).integrate(path, lib, destination, root)
    raw = path.read_bytes()
    second = getattr(ide, backend).integrate(path, lib, destination, root)

    assert LFS.encode() in raw
    assert re.search(rb"(?<!\r)\n", raw) is None, "a line ends with a bare line feed"
    assert second.status == ide.ALREADY
    assert path.read_bytes() == raw


@pytest.mark.parametrize("backend, where, options", BACKENDS)
def test_a_library_without_defines_leaves_the_define_list_alone(backend, where, options, library, project):
    """What every library installed before this one does, and must keep doing."""
    root = project(**options)
    path = root / where
    lib, destination = _install(library, root, defines=())

    getattr(ide, backend).integrate(path, lib, destination, root)
    text = path.read_text(encoding="utf-8")

    assert "STM32G431xx" in text
    assert "LFS" not in text


# ----------------------------------------------------------------------------
# The record, and an update from start to finish.
# ----------------------------------------------------------------------------


def test_the_record_keeps_the_defines(library, tmp_path):
    lib = manifest.load(library(install={"defines": [LFS]}))
    root = tmp_path / "Proj"

    installer.install_to(lib, root / "demo", project_root=root)
    record = json.loads((root / installer.RECORD_NAME).read_text(encoding="utf-8"))

    assert record["libraries"]["demo"]["defines"] == [LFS]


def test_an_update_lists_the_defines_the_library_dropped(library, tmp_path):
    root = tmp_path / "Proj"
    old = manifest.load(library(install={"defines": ["LFS_DEFINES=old.h", "DEMO_FAST"]}, root=tmp_path / "v1"))
    new = manifest.load(library(install={"defines": [LFS, "DEMO_FAST"]}, root=tmp_path / "v2"))

    installer.install_to(old, root / "demo", project_root=root)
    result = installer.install_to(new, root / "demo", project_root=root)

    assert result.dropped_defines == ["LFS_DEFINES=old.h"]


def test_a_define_edited_into_the_record_is_never_used(library, tmp_path):
    """The record is a file in the user's project, so it is not trusted."""
    root = tmp_path / "Proj"
    lib = manifest.load(library(install={"defines": [LFS]}))
    installer.install_to(lib, root / "demo", project_root=root)

    path = root / installer.RECORD_NAME
    record = json.loads(path.read_text(encoding="utf-8"))
    record["libraries"]["demo"]["defines"] = ['X"/><evil', 7, "OLD_ONE"]
    path.write_text(json.dumps(record), encoding="utf-8")

    result = installer.install_to(lib, root / "demo", project_root=root)

    assert result.dropped_defines == ["OLD_ONE"]


def test_a_copy_in_another_folder_drops_nothing(library, tmp_path):
    root = tmp_path / "Proj"
    installer.install_to(manifest.load(library(install={"defines": [LFS]})), root / "demo", project_root=root)

    lib = manifest.load(library(install={"defines": []}, root=tmp_path / "v2"))
    result = installer.install_to(lib, root / "other", project_root=root)

    assert result.dropped_defines == []


def test_an_update_through_the_command_line_moves_the_define(library, project, tmp_path, no_network):
    """The whole path: record, result, and every IDE told what to take out."""
    root = project(cmake=True, cubeide=True, keil=True, iar=True, makefile=True)
    old = library(install={"defines": ["LFS_DEFINES=old.h"]}, root=tmp_path / "v1")
    new = library(install={"defines": [LFS]}, root=tmp_path / "v2")

    assert cli.main([str(old), "--project", str(root), "--dir", "demo"]) == 0
    assert cli.main([str(new), "--project", str(root), "--dir", "demo"]) == 0

    for where in (".cproject", "MDK/Proj.uvprojx", "EWARM/Proj.ewp", "Makefile", "demo/CMakeLists.txt"):
        text = (root / where).read_text(encoding="utf-8")

        assert LFS in text, where
        assert "old.h" not in text, where
