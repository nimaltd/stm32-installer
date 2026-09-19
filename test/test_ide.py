"""Tests for registering a library with each IDE."""

from stm32_installer import ide, manifest
from stm32_installer.ide import cmake, cubeide, iar, keil


def _install(library_factory, project_root, **kwargs):
    """A library on disk plus the folder it would be installed into."""
    lib = manifest.load(library_factory(**kwargs))

    return lib, project_root / "demo"


def test_nothing_is_recognised_in_an_empty_folder(tmp_path):
    assert ide.detect(tmp_path) == []


def test_a_cubemx_cmake_project_is_both_cmake_and_cubeide(project):
    root = project(cmake=True, cubeide=True)

    names = {backend.NAME for backend, _ in ide.detect(root)}

    assert names == {"CMake", "STM32CubeIDE"}


def test_cmake_block_lists_sources_and_include_path(library, project):
    root = project(cmake=True)
    lib, destination = _install(library, root)

    outcome = cmake.integrate(root / "CMakeLists.txt", lib, destination, root)
    text = (root / "CMakeLists.txt").read_text(encoding="utf-8")

    assert outcome.status == ide.CHANGED
    assert "demo/demo.c" in text
    assert "target_include_directories(${CMAKE_PROJECT_NAME} PRIVATE demo)" in text


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
        extra_files={"src/demo_port_template.c": "/* port */\n"},
        config=[
            {"from": "inc/demo_config_template.h", "to": "demo_config.h"},
            {"from": "src/demo_port_template.c", "to": "demo_port.c"},
        ],
    )

    cmake.integrate(root / "CMakeLists.txt", lib, destination, root)
    keil.integrate(root / "MDK" / "Proj.uvprojx", lib, destination, root)
    iar.integrate(root / "EWARM" / "Proj.ewp", lib, destination, root)

    assert "demo/demo_port.c" in (root / "CMakeLists.txt").read_text(encoding="utf-8")
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
