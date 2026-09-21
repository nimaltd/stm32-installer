"""Tests for registering a library with each IDE."""

import re

import pytest

from stm32_installer import ide, manifest
from stm32_installer.ide import cmake, cubeide, iar, keil


def _install(library_factory, project_root, **kwargs):
    """
    A library on disk plus the folder it is installed into.

    The folder is created here because the real flow creates it before any IDE
    is touched, and the CMake integration writes a file into it.
    """
    lib = manifest.load(library_factory(**kwargs))
    destination = project_root / "demo"
    destination.mkdir(parents=True, exist_ok=True)

    return lib, destination


def test_nothing_is_recognised_in_an_empty_folder(tmp_path):
    assert ide.detect(tmp_path) == []


def test_a_cubemx_cmake_project_is_both_cmake_and_cubeide(project):
    root = project(cmake=True, cubeide=True)

    names = {backend.NAME for backend, _ in ide.detect(root)}

    assert names == {"CMake", "STM32CubeIDE"}


def test_cmake_block_points_at_the_library_folder(library, project):
    """The project file gets two lines, not a list that grows with the library."""
    root = project(cmake=True)
    lib, destination = _install(library, root)

    outcome = cmake.integrate(root / "CMakeLists.txt", lib, destination, root)
    text = (root / "CMakeLists.txt").read_text(encoding="utf-8")

    assert outcome.status == ide.CHANGED
    assert "add_subdirectory(demo)" in text
    assert "target_link_libraries(${CMAKE_PROJECT_NAME} PRIVATE demo_lib)" in text
    assert "demo.c" not in text


def test_the_library_gets_its_own_cmakelists(library, project):
    """
    The target must be INTERFACE. A STATIC one would not inherit the
    application's defines and include paths, so a driver including main.h would
    fail to compile. That is the whole reason this file is generated.
    """
    root = project(cmake=True)
    lib, destination = _install(library, root)

    cmake.integrate(root / "CMakeLists.txt", lib, destination, root)
    text = (destination / "CMakeLists.txt").read_text(encoding="utf-8")

    assert "add_library(demo_lib INTERFACE)" in text
    assert "add_library(demo_lib STATIC" not in text
    assert "${CMAKE_CURRENT_SOURCE_DIR}/demo.c" in text


def test_cmake_block_is_replaced_not_repeated(library, project):
    root = project(cmake=True)
    lib, destination = _install(library, root)

    cmake.integrate(root / "CMakeLists.txt", lib, destination, root)
    second = cmake.integrate(root / "CMakeLists.txt", lib, destination, root)
    text = (root / "CMakeLists.txt").read_text(encoding="utf-8")

    assert second.status == ide.ALREADY
    assert text.count(">>> stm32-installer: demo >>>") == 1


def test_cmake_refuses_a_file_it_does_not_understand(library, project, tmp_path):
    root = project(cmake=True)
    (root / "CMakeLists.txt").write_text("# nothing useful here\n", encoding="utf-8")
    lib, destination = _install(library, root)

    outcome = cmake.integrate(root / "CMakeLists.txt", lib, destination, root)

    assert outcome.status == ide.MANUAL
    assert outcome.steps


def test_cubeide_adds_the_path_to_every_configuration(library, project):
    root = project(cubeide=True)
    lib, destination = _install(library, root)

    outcome = cubeide.integrate(root / ".cproject", lib, destination, root)
    text = (root / ".cproject").read_text(encoding="utf-8")

    assert outcome.status == ide.CHANGED
    assert text.count('value="../demo"') == 2


def test_cubeide_keeps_the_file_version_line(library, project):
    """ElementTree drops this line, and a .cproject without it will not open."""
    root = project(cubeide=True)
    lib, destination = _install(library, root)

    cubeide.integrate(root / ".cproject", lib, destination, root)

    assert "<?fileVersion 4.0.0?>" in (root / ".cproject").read_text(encoding="utf-8")


def test_cubeide_does_not_add_the_path_twice(library, project):
    root = project(cubeide=True)
    lib, destination = _install(library, root)

    cubeide.integrate(root / ".cproject", lib, destination, root)
    second = cubeide.integrate(root / ".cproject", lib, destination, root)

    assert second.status == ide.ALREADY


def test_keil_uses_a_relative_path_from_its_own_subfolder(library, project):
    """The .uvprojx lives in MDK/, so the library is one level up from it."""
    root = project(keil=True)
    lib, destination = _install(library, root)

    outcome = keil.integrate(root / "MDK" / "Proj.uvprojx", lib, destination, root)
    text = (root / "MDK" / "Proj.uvprojx").read_text(encoding="utf-8")

    assert outcome.status == ide.CHANGED
    assert "..\\demo\\demo.c" in text
    assert "..\\Core\\Inc;..\\demo" in text


def test_iar_uses_a_relative_path_from_its_own_subfolder(library, project):
    root = project(iar=True)
    lib, destination = _install(library, root)

    outcome = iar.integrate(root / "EWARM" / "Proj.ewp", lib, destination, root)
    text = (root / "EWARM" / "Proj.ewp").read_text(encoding="utf-8")

    assert outcome.status == ide.CHANGED
    assert "$PROJ_DIR$\\..\\demo\\demo.c" in text
    assert "<state>$PROJ_DIR$/../demo</state>" in text


def test_a_c_template_reaches_every_build(library, project):
    """A port layer shipped as a template is a source like any other."""
    root = project(cmake=True, keil=True, iar=True)
    lib, destination = _install(
        library,
        root,
        extra_files={"template/demo_port.c": "/* port */\n"},
        once=[
            {"from": "template/demo_config.h"},
            {"from": "template/demo_port.c"},
        ],
    )

    cmake.integrate(root / "CMakeLists.txt", lib, destination, root)
    keil.integrate(root / "MDK" / "Proj.uvprojx", lib, destination, root)
    iar.integrate(root / "EWARM" / "Proj.ewp", lib, destination, root)

    # For CMake the file list now lives in the library's own CMakeLists.txt.
    assert "demo_port.c" in (destination / "CMakeLists.txt").read_text(encoding="utf-8")
    assert "demo_port.c" in (root / "MDK" / "Proj.uvprojx").read_text(encoding="utf-8")
    assert "demo_port.c" in (root / "EWARM" / "Proj.ewp").read_text(encoding="utf-8")


def test_every_edit_leaves_a_backup(library, project):
    root = project(cmake=True)
    lib, destination = _install(library, root)

    outcome = cmake.integrate(root / "CMakeLists.txt", lib, destination, root)

    assert outcome.backup is not None
    assert outcome.backup.is_file()
    assert "add_executable" in outcome.backup.read_text(encoding="utf-8")


def test_integrate_runs_every_backend_that_matches(library, project):
    root = project(cmake=True, cubeide=True, keil=True, iar=True)
    lib, destination = _install(library, root)

    outcomes = ide.integrate(root, lib, destination)

    assert len(outcomes) == 4
    assert all(o.status == ide.CHANGED for o in outcomes)


def test_only_one_backend_can_be_selected(library, project):
    root = project(cmake=True, cubeide=True)
    lib, destination = _install(library, root)

    outcomes = ide.integrate(root, lib, destination, only="cmake")

    assert [o.ide for o in outcomes] == ["CMake"]


def test_the_library_target_does_not_clash_with_the_project(library, project):
    """
    Found in a real CubeMX project called fsm, testing the fsm library.

    CMake allows one target per name, so naming the library target after the
    library collided with the executable and the configure step failed with
    "another target with the same name already exists".
    """
    root = project(cmake=True)
    (root / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.22)\n"
        "set(CMAKE_PROJECT_NAME demo)\n"
        "project(${CMAKE_PROJECT_NAME})\n"
        "add_executable(${CMAKE_PROJECT_NAME})\n",
        encoding="utf-8",
    )
    lib, destination = _install(library, root)

    cmake.integrate(root / "CMakeLists.txt", lib, destination, root)

    assert "add_library(demo_lib INTERFACE)" in (destination / "CMakeLists.txt").read_text(
        encoding="utf-8"
    )
    assert "add_library(demo INTERFACE)" not in (destination / "CMakeLists.txt").read_text(
        encoding="utf-8"
    )


def test_a_plain_link_signature_is_matched(library, project):
    """
    The CubeMX template links without a keyword, and CMake refuses to mix the
    two forms on one target. Adding PRIVATE broke every CubeMX CMake project
    with "the plain signature has already been used with the target".
    """
    root = project(cmake=True)
    (root / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.22)\n"
        "project(Proj C)\n"
        "add_executable(${CMAKE_PROJECT_NAME})\n"
        "target_link_libraries(${CMAKE_PROJECT_NAME}\n    stm32cubemx\n)\n",
        encoding="utf-8",
    )
    lib, destination = _install(library, root)

    cmake.integrate(root / "CMakeLists.txt", lib, destination, root)
    text = (root / "CMakeLists.txt").read_text(encoding="utf-8")

    assert "target_link_libraries(${CMAKE_PROJECT_NAME} demo_lib)" in text
    assert "PRIVATE demo_lib" not in text


def test_a_keyword_link_signature_is_matched_too(library, project):
    root = project(cmake=True)
    (root / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.22)\n"
        "project(Proj C)\n"
        "add_executable(app main.c)\n"
        "target_link_libraries(app PRIVATE something)\n",
        encoding="utf-8",
    )
    lib, destination = _install(library, root)

    cmake.integrate(root / "CMakeLists.txt", lib, destination, root)

    assert "target_link_libraries(app PRIVATE demo_lib)" in (
        root / "CMakeLists.txt"
    ).read_text(encoding="utf-8")


def test_reinstalling_does_not_flip_the_signature(library, project):
    """The tool must not read its own previous block back as evidence."""
    root = project(cmake=True)
    (root / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.22)\n"
        "project(Proj C)\n"
        "add_executable(${CMAKE_PROJECT_NAME})\n"
        "target_link_libraries(${CMAKE_PROJECT_NAME}\n    stm32cubemx\n)\n",
        encoding="utf-8",
    )
    lib, destination = _install(library, root)

    cmake.integrate(root / "CMakeLists.txt", lib, destination, root)
    cmake.integrate(root / "CMakeLists.txt", lib, destination, root)
    text = (root / "CMakeLists.txt").read_text(encoding="utf-8")

    assert "PRIVATE demo_lib" not in text
    assert text.count("demo_lib") == 1
# ----------------------------------------------------------------------------
# The shape of the edit.
#
# A project file is read by people and lands in version control, so an added
# line has to come out looking like the lines around it. Every check below
# comes from a real .cproject that came back from a user: the library was on
# the include path and the build worked, but the line had been written hard
# against the left margin while every line around it was nine tabs in.
# ----------------------------------------------------------------------------


def _added_lines(before, after):
    """The lines that appear in after and not in before, in order."""
    old = before.splitlines()
    new = after.splitlines()
    counts = {}

    for line in old:
        counts[line] = counts.get(line, 0) + 1

    added = []

    for line in new:
        if counts.get(line, 0) > 0:
            counts[line] -= 1
        else:
            added.append(line)

    return added


def _indent(line):
    return line[: len(line) - len(line.lstrip(" \t"))]


def test_cubeide_lines_up_with_the_paths_already_there(library, project):
    """The reason this file exists. See the comment above."""
    root = project(cubeide=True)
    lib, destination = _install(library, root)
    before = (root / ".cproject").read_text(encoding="utf-8")

    cubeide.integrate(root / ".cproject", lib, destination, root)
    after = (root / ".cproject").read_text(encoding="utf-8")

    existing = [ln for ln in before.splitlines() if "../Core/Inc" in ln]
    added = _added_lines(before, after)

    assert len(added) == 2
    assert all(_indent(line) == _indent(existing[0]) for line in added)
    assert _indent(existing[0]) != ""


def test_cubeide_puts_the_path_after_the_ones_already_there(library, project):
    """Where CubeIDE itself puts one added through the Properties dialog."""
    root = project(cubeide=True)
    lib, destination = _install(library, root)

    cubeide.integrate(root / ".cproject", lib, destination, root)
    text = (root / ".cproject").read_text(encoding="utf-8")

    assert text.index('value="../Drivers/CMSIS/Include"') < text.index('value="../demo"')


def test_cubeide_fills_in_a_configuration_the_other_already_has(library, project):
    """
    Half a project is the case a whole file check gets wrong.

    Asking "is the path anywhere in this file" says yes as soon as Debug has
    it, and Release is then left without it. That shows up much later as a
    build that works in one configuration and not the other.
    """
    root = project(cubeide=True)
    lib, destination = _install(library, root)

    cubeide.integrate(root / ".cproject", lib, destination, root)

    # Take it back out of the Release configuration only.
    text = (root / ".cproject").read_text(encoding="utf-8")
    cut = text.rindex('<listOptionValue builtIn="false" value="../demo"/>')
    line = text.rindex("\n", 0, cut)
    (root / ".cproject").write_text(
        text[:line] + text[cut + len('<listOptionValue builtIn="false" value="../demo"/>'):],
        encoding="utf-8",
    )

    outcome = cubeide.integrate(root / ".cproject", lib, destination, root)
    text = (root / ".cproject").read_text(encoding="utf-8")

    assert outcome.status == ide.CHANGED
    assert text.count('value="../demo"') == 2


def test_keil_lines_up_with_the_groups_already_there(library, project):
    root = project(keil=True)
    lib, destination = _install(library, root)
    path = root / "MDK" / "Proj.uvprojx"
    before = path.read_text(encoding="utf-8")

    keil.integrate(path, lib, destination, root)
    after = path.read_text(encoding="utf-8")

    added = {ln.split("<")[1].split(">")[0]: _indent(ln) for ln in _added_lines(before, after)}
    kept = {ln.split("<")[1].split(">")[0]: _indent(ln) for ln in before.splitlines() if "<" in ln}

    for tag in ("Group", "Files", "File", "FileName"):
        assert added[tag] == kept[tag], f"{tag} does not line up with the one already there"


def test_keil_puts_the_group_after_the_ones_already_there(library, project):
    """Where uVision puts one added through Manage Project Items."""
    root = project(keil=True)
    lib, destination = _install(library, root)
    path = root / "MDK" / "Proj.uvprojx"

    keil.integrate(path, lib, destination, root)
    text = path.read_text(encoding="utf-8")

    assert text.index("<GroupName>Application/User/Core</GroupName>") < text.index(
        "<GroupName>demo</GroupName>"
    )


def test_keil_follows_the_slash_the_project_uses(library, project):
    """
    CubeMX writes forward slashes and uVision writes backslashes.

    Keil reads either, so the one to write is whichever is already in the file.
    The default fixture is the uVision form, so this covers the other one.
    """
    root = project(keil=True)
    path = root / "MDK" / "Proj.uvprojx"
    path.write_text(
        path.read_text(encoding="utf-8").replace("\\", "/"), encoding="utf-8"
    )
    lib, destination = _install(library, root)

    keil.integrate(path, lib, destination, root)
    text = path.read_text(encoding="utf-8")

    assert "<FilePath>../demo/demo.c</FilePath>" in text
    assert "..\\demo" not in text


def test_iar_lines_up_with_what_is_already_there(library, project):
    root = project(iar=True)
    lib, destination = _install(library, root)
    path = root / "EWARM" / "Proj.ewp"
    before = path.read_text(encoding="utf-8")

    iar.integrate(path, lib, destination, root)
    after = path.read_text(encoding="utf-8")

    added = _added_lines(before, after)
    kept = before.splitlines()

    state = [ln for ln in added if "<state>" in ln]
    group = [ln for ln in added if "<group>" in ln]
    file_name = [ln for ln in added if "$PROJ_DIR$" in ln and "<name>" in ln]

    assert _indent(state[0]) == _indent([ln for ln in kept if "<state>" in ln][0])
    assert _indent(group[0]) == _indent([ln for ln in kept if "<group>" in ln][0])
    # The shallowest, because the new group is a top level one. Comparing
    # against a file nested three groups deep would demand that depth of it.
    assert _indent(file_name[0]) == min(
        (_indent(ln) for ln in kept if "$PROJ_DIR$" in ln and "<name>" in ln), key=len
    )


def test_iar_follows_the_slash_the_project_uses(library, project):
    """Embedded Workbench on Windows writes backslashes throughout."""
    root = project(iar=True)
    path = root / "EWARM" / "Proj.ewp"
    path.write_text(
        path.read_text(encoding="utf-8")
        .replace("$PROJ_DIR$/../Core/Inc", "$PROJ_DIR$\\..\\Core\\Inc")
        .replace("$PROJ_DIR$/../Drivers/CMSIS/Include", "$PROJ_DIR$\\..\\Drivers\\CMSIS\\Include"),
        encoding="utf-8",
    )
    lib, destination = _install(library, root)

    iar.integrate(path, lib, destination, root)
    text = path.read_text(encoding="utf-8")

    assert "<state>$PROJ_DIR$\\..\\demo</state>" in text
    assert "$PROJ_DIR$/../demo" not in text


CRLF_CASES = [
    ("cmake", "CMakeLists.txt", lambda root: dict(cmake=True)),
    ("cubeide", ".cproject", lambda root: dict(cubeide=True)),
    ("keil", "MDK/Proj.uvprojx", lambda root: dict(keil=True)),
    ("iar", "EWARM/Proj.ewp", lambda root: dict(iar=True)),
]


@pytest.mark.parametrize("backend, where, options", CRLF_CASES)
def test_a_crlf_project_stays_crlf(backend, where, options, library, project):
    """
    CubeMX writes CRLF on Windows, and these files are under version control.

    Path.read_text folds CRLF into LF and Path.write_text unfolds it again on
    Windows and not anywhere else, so an integration that goes through them
    rewrites every line ending in the file to add one line to it. On Windows
    that quietly happens to come out right, which is why it has to be checked
    here rather than noticed in use.
    """
    root = project(newline="\r\n", **options(None))
    lib, destination = _install(library, root)
    path = root / where

    getattr(ide, backend).integrate(path, lib, destination, root)
    raw = path.read_bytes()

    assert re.search(rb"(?<!\r)\n", raw) is None, "a line ends with a bare line feed"
    assert re.search(rb"\r(?!\n)", raw) is None, "a carriage return lost its line feed"
    assert raw.count(b"\r\n") > 0


@pytest.mark.parametrize("backend, where, options", CRLF_CASES)
def test_a_second_run_on_a_crlf_project_changes_nothing(backend, where, options, library, project):
    """
    Idempotence has to survive CRLF too.

    A block built with line feeds never compares equal to the same block stored
    with CRLF, so the integration would decide it had to write the file again,
    and take a fresh backup, on every single run.
    """
    root = project(newline="\r\n", **options(None))
    lib, destination = _install(library, root)
    path = root / where

    getattr(ide, backend).integrate(path, lib, destination, root)
    once = path.read_bytes()

    outcome = getattr(ide, backend).integrate(path, lib, destination, root)

    assert outcome.status == ide.ALREADY
    assert path.read_bytes() == once
# ----------------------------------------------------------------------------
# Which file is the project.
#
# From a real G431 board. IAR had upgraded the project and left "Backup of
# STM32G431CBU6.ewp" beside it. The installer globbed for *.ewp, took the first
# by name, and put the library into the backup. It printed that it had succeeded
# and named a file that looked right, and the project he actually builds was
# never touched.
# ----------------------------------------------------------------------------


def test_iar_ignores_the_backup_the_ide_left_behind(library, project):
    """The reason this file exists. See the comment above."""
    root = project(iar=True, iar_backup=True)
    stale = root / "EWARM" / "Backup of Proj.ewp"
    before = stale.read_bytes()
    lib, destination = _install(library, root)

    found = iar.detect(root)
    iar.integrate(found, lib, destination, root)

    assert found.name == "Proj.ewp"
    assert stale.read_bytes() == before, "the backup was edited"
    assert "demo" in (root / "EWARM" / "Proj.ewp").read_text(encoding="utf-8")


def test_keil_ignores_the_backup_the_ide_left_behind(library, project):
    root = project(keil=True, keil_backup=True)

    assert ide.keil.detect(root).name == "Proj.uvprojx"


def test_iar_asks_the_workspace_which_project_is_real(library, project):
    """
    A workspace names its project, so there is no need to guess at all.

    Renaming the real project to sort last proves the answer comes from the
    workspace rather than from the order the glob happens to return.
    """
    root = project(iar=True)
    ewarm = root / "EWARM"
    (ewarm / "Proj.ewp").rename(ewarm / "zzz.ewp")
    (ewarm / "Project.eww").write_text(
        (ewarm / "Project.eww").read_text(encoding="utf-8").replace("Proj.ewp", "zzz.ewp"),
        encoding="utf-8",
    )
    (ewarm / "Aaa.ewp").write_text("<project></project>\n", encoding="utf-8")

    assert iar.detect(root).name == "zzz.ewp"


def test_iar_follows_the_slash_of_the_section_it_is_editing(library, project):
    """
    CubeMX uses both slashes in one .ewp.

    The include paths are written with forward slashes and the file list with
    backslashes, so asking the file as a whole gets one of the two wrong. On the
    real G431 project it put a backslash path among eight forward slash ones.
    """
    root = project(iar=True)
    lib, destination = _install(library, root)
    path = root / "EWARM" / "Proj.ewp"

    iar.integrate(path, lib, destination, root)
    text = path.read_text(encoding="utf-8")

    assert "<state>$PROJ_DIR$/../demo</state>" in text
    assert "<name>$PROJ_DIR$\\..\\demo\\demo.c</name>" in text


def test_iar_lines_up_with_a_nested_group(library, project):
    """
    Groups nest, and a <group>...</group> regex closes on a child's tag.

    Matching Application against the </group> that belongs to Core reads the
    indentation off the wrong level, so the new group lands at a depth nothing
    else in the file uses.
    """
    root = project(iar=True)
    lib, destination = _install(library, root)
    path = root / "EWARM" / "Proj.ewp"
    before = path.read_text(encoding="utf-8")

    iar.integrate(path, lib, destination, root)
    after = path.read_text(encoding="utf-8")

    top = [_indent(ln) for ln in before.splitlines() if ln.strip() == "<group>"]
    added = [_indent(ln) for ln in _added_lines(before, after) if ln.strip() == "<group>"]

    assert added == [min(top, key=len)]


def test_iar_keeps_the_ewt_in_step_with_the_ewp(library, project):
    """IAR mirrors the file tree into the .ewt beside the project."""
    root = project(iar=True)
    lib, destination = _install(library, root)

    iar.integrate(root / "EWARM" / "Proj.ewp", lib, destination, root)
    ewt = (root / "EWARM" / "Proj.ewt").read_text(encoding="utf-8")

    assert "<name>demo</name>" in ewt
    assert "$PROJ_DIR$\\..\\demo\\demo.c" in ewt


def test_iar_is_fine_without_an_ewt(library, project):
    """Older workbenches do not write one, and that is not an error."""
    root = project(iar=True)
    (root / "EWARM" / "Proj.ewt").unlink()
    lib, destination = _install(library, root)

    outcome = iar.integrate(root / "EWARM" / "Proj.ewp", lib, destination, root)

    assert outcome.status == ide.CHANGED
def test_only_compilable_files_reach_an_ide_file_group(library, project):
    """
    Keil and IAR name every file in the project, so the group is the file tree.

    Anything that lands in it is shown to the user and handed to the compiler.
    A README in there is confusing at best, so the filter covers a manifest
    that lists a non-source under `sources`, not only the `once` entries.
    """
    root = project(keil=True, iar=True)
    lib, destination = _install(
        library,
        root,
        sources=("src/demo.c", "README.md"),
        extra_files={"README.md": "# demo\n"},
    )

    assert lib.build_sources == ["demo.c"]

    keil.integrate(root / "MDK" / "Proj.uvprojx", lib, destination, root)
    iar.integrate(root / "EWARM" / "Proj.ewp", lib, destination, root)

    assert "README" not in (root / "MDK" / "Proj.uvprojx").read_text(encoding="utf-8")
    assert "README" not in (root / "EWARM" / "Proj.ewp").read_text(encoding="utf-8")
# ----------------------------------------------------------------------------
# Knowing the library is already there, without a marker in its name.
# ----------------------------------------------------------------------------


def test_the_group_is_named_after_the_library_and_nothing_else(library, project):
    """That name is read by the user in the project tree every day."""
    root = project(keil=True, iar=True)
    lib, destination = _install(library, root)

    keil.integrate(root / "MDK" / "Proj.uvprojx", lib, destination, root)
    iar.integrate(root / "EWARM" / "Proj.ewp", lib, destination, root)

    uvprojx = (root / "MDK" / "Proj.uvprojx").read_text(encoding="utf-8")
    ewp = (root / "EWARM" / "Proj.ewp").read_text(encoding="utf-8")

    assert "<GroupName>demo</GroupName>" in uvprojx
    assert "<name>demo</name>" in ewp
    assert "stm32-installer" not in uvprojx
    assert "stm32-installer" not in ewp


@pytest.mark.parametrize("backend, where", [("keil", "MDK/Proj.uvprojx"),
                                            ("iar", "EWARM/Proj.ewp")])
def test_a_renamed_group_is_still_recognised(backend, where, library, project):
    """
    The user owns that name once the files are in their project.

    A marker in the name would make a rename look like a fresh install, and the
    second run would add every file a second time. Asking whether the files are
    in the project does not care what the group around them is called.
    """
    root = project(keil=True, iar=True)
    lib, destination = _install(library, root)
    path = root / where

    getattr(ide, backend).integrate(path, lib, destination, root)
    path.write_text(
        path.read_text(encoding="utf-8").replace(">demo<", ">My own name<"), encoding="utf-8"
    )
    before = path.read_text(encoding="utf-8")

    outcome = getattr(ide, backend).integrate(path, lib, destination, root)

    assert outcome.status == ide.ALREADY
    assert path.read_text(encoding="utf-8") == before
    # The path, not the bare name: Keil writes the name in <FileName> as well.
    assert before.count("demo\\demo.c") == 1


@pytest.mark.parametrize("backend, where", [("keil", "MDK/Proj.uvprojx"),
                                            ("iar", "EWARM/Proj.ewp")])
def test_a_header_only_library_gets_no_empty_group(backend, where, library, project):
    """
    With nothing to compile there is no file to recognise the library by.

    An empty group would therefore be added again on every single run, and the
    project tree would fill up with copies of it.
    """
    root = project(keil=True, iar=True)
    lib, destination = _install(library, root, sources=(), once=[])
    path = root / where

    first = getattr(ide, backend).integrate(path, lib, destination, root)
    second = getattr(ide, backend).integrate(path, lib, destination, root)
    text = path.read_text(encoding="utf-8")

    assert first.status == ide.CHANGED, "the include path still has to be added"
    assert second.status == ide.ALREADY
    assert "demo" in text, "the include path is there"
    assert text.count(">demo<") == 0, "but no group was created for it"
