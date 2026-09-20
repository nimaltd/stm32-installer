"""Tests for registering a library with each IDE."""

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
    assert "$PROJ_DIR$/../demo/demo.c" in text
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
