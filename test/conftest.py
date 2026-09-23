"""Shared fixtures: a throwaway library repository and a throwaway STM32 project."""

import sys
from pathlib import Path

import pytest
import yaml

SRC = Path(__file__).resolve().parent.parent / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture
def library(tmp_path):
    """
    Build a library repository on disk and return its path.

    Every argument has a working default, so a test states only the part it
    cares about.
    """

    def build(
        name="demo",
        version="1.0.0",
        kind="driver",
        headers=("inc/demo.h",),
        sources=("src/demo.c",),
        once=None,
        requires=None,
        install=None,
        extra_files=None,
        root=None,
    ):
        root = Path(root) if root else tmp_path / name
        root.mkdir(parents=True, exist_ok=True)

        if once is None:
            once = [{"from": "template/demo_config.h"}]

        written = {
            "template/demo_config.h": "#define DEMO_SIZE 8\n",
            "NOTICE": f"{name}\nCopyright 2026 Nima Askari (NimaLTD)\n",
        }
        # A files entry is either a plain path, a wildcard, or a {from, to}
        # pair. Only the "from" side is a file, and a wildcard names no file of
        # its own, so a test using one supplies the real files in extra_files.
        def source_of(item):
            name = item["from"] if isinstance(item, dict) else item

            return None if any(ch in str(name) for ch in "*?[") else name

        written.update({source_of(h): "/* header */\n" for h in headers if source_of(h)})
        written.update({source_of(s): "/* source */\n" for s in sources if source_of(s)})
        written.update(extra_files or {})

        for relative, text in written.items():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")

        data = {"name": name}

        # None leaves the key out entirely, the way a library.yml looks now that
        # the version is read from the header instead.
        if version is not None:
            data["version"] = version

        data["kind"] = kind
        data["files"] = {"headers": list(headers), "sources": list(sources)}

        if once:
            data["once"] = once

        if requires:
            data["requires"] = requires

        if install:
            data["install"] = install

        (root / "library.yml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

        return root

    return build


# The project files below are nested and indented the way the real tools write
# them, tabs in a .cproject and spaces in the other two, because what these
# fixtures are used to check is that an added line comes out looking like the
# lines around it. A flat fixture cannot tell a right answer from a wrong one.

CPROJECT = (
    '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
    "<?fileVersion 4.0.0?><cproject>\n"
    "\t<storageModule moduleId=\"cdtBuildSystem\">\n"
    "\t\t<configuration name=\"Debug\">\n"
    "\t\t\t<toolChain>\n"
    "\t\t\t\t<tool>\n"
    "\t\t\t\t\t<option id=\"a\" superClass=\"x.c.compiler.option.includepaths\""
    " valueType=\"includePath\">\n"
    "\t\t\t\t\t\t<listOptionValue builtIn=\"false\" value=\"../Core/Inc\"/>\n"
    "\t\t\t\t\t\t<listOptionValue builtIn=\"false\" value=\"../Drivers/CMSIS/Include\"/>\n"
    "\t\t\t\t\t</option>\n"
    "\t\t\t\t\t<option id=\"opt\" superClass=\"x.c.compiler.option.optimization.level\"/>\n"
    "\t\t\t\t</tool>\n"
    "\t\t\t</toolChain>\n"
    "\t\t</configuration>\n"
    "\t\t<configuration name=\"Release\">\n"
    "\t\t\t<toolChain>\n"
    "\t\t\t\t<tool>\n"
    "\t\t\t\t\t<option id=\"b\" superClass=\"x.c.compiler.option.includepaths\""
    " valueType=\"includePath\">\n"
    "\t\t\t\t\t\t<listOptionValue builtIn=\"false\" value=\"../Core/Inc\"/>\n"
    "\t\t\t\t\t\t<listOptionValue builtIn=\"false\" value=\"../Drivers/CMSIS/Include\"/>\n"
    "\t\t\t\t\t</option>\n"
    "\t\t\t\t</tool>\n"
    "\t\t\t</toolChain>\n"
    "\t\t</configuration>\n"
    "\t</storageModule>\n"
    "</cproject>\n"
)

# Backslash paths, which is what uVision writes once a path has been added
# through its own dialogs. The CubeMX generated form uses forward slashes and
# has its own test.
UVPROJX = (
    '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
    "<Project>\n"
    "  <Targets>\n"
    "    <Target>\n"
    "      <TargetOption>\n"
    "        <TargetArmAds>\n"
    "          <Cads>\n"
    "            <VariousControls>\n"
    "              <IncludePath>..\\Core\\Inc</IncludePath>\n"
    "            </VariousControls>\n"
    "          </Cads>\n"
    "        </TargetArmAds>\n"
    "      </TargetOption>\n"
    "      <Groups>\n"
    "        <Group>\n"
    "          <GroupName>Application/User/Core</GroupName>\n"
    "          <Files>\n"
    "            <File>\n"
    "              <FileName>main.c</FileName>\n"
    "              <FileType>1</FileType>\n"
    "              <FilePath>..\\Core\\Src\\main.c</FilePath>\n"
    "            </File>\n"
    "          </Files>\n"
    "        </Group>\n"
    "      </Groups>\n"
    "    </Target>\n"
    "  </Targets>\n"
    "</Project>\n"
)

# Four space indentation, groups nested inside groups, and the two slashes
# mixed: forward in the include paths, back in the file list. All three come
# straight from a CubeMX generated EWARM project, and all three were getting
# the integration wrong until a real one was looked at.
EWP = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<project>\n"
    "    <fileVersion>4</fileVersion>\n"
    "    <configuration>\n"
    "        <name>Proj</name>\n"
    "        <settings>\n"
    "            <name>ICCARM</name>\n"
    "            <data>\n"
    "                <option>\n"
    "                    <name>CCIncludePath2</name>\n"
    "                    <state>$PROJ_DIR$/../Core/Inc</state>\n"
    "                    <state>$PROJ_DIR$/../Drivers/CMSIS/Include</state>\n"
    "                </option>\n"
    "            </data>\n"
    "        </settings>\n"
    "    </configuration>\n"
    "    <group>\n"
    "        <name>Application</name>\n"
    "        <group>\n"
    "            <name>User</name>\n"
    "            <group>\n"
    "                <name>Core</name>\n"
    "                <file>\n"
    "                    <name>$PROJ_DIR$\\..\\Core\\Src\\main.c</name>\n"
    "                </file>\n"
    "            </group>\n"
    "        </group>\n"
    "    </group>\n"
    "    <group>\n"
    "        <name>Drivers</name>\n"
    "        <file>\n"
    "            <name>$PROJ_DIR$\\..\\Drivers\\stm32g4xx_hal.c</name>\n"
    "        </file>\n"
    "        <file>\n"
    "            <name>$PROJ_DIR$\\..\\Drivers\\stm32g4xx_hal_rcc.c</name>\n"
    "        </file>\n"
    "        <file>\n"
    "            <name>$PROJ_DIR$\\..\\Drivers\\stm32g4xx_hal_gpio.c</name>\n"
    "        </file>\n"
    "        <file>\n"
    "            <name>$PROJ_DIR$\\..\\Drivers\\stm32g4xx_hal_tim.c</name>\n"
    "        </file>\n"
    "    </group>\n"
    "</project>\n"
)

# The workspace, which is what says which .ewp is the real project.
EWW = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<workspace>\n"
    "  <project>\n"
    "    <path>$WS_DIR$\\Proj.ewp</path>\n"
    "  </project>\n"
    "  <batchBuild />\n"
    "</workspace>\n"
)

# The companion IAR keeps beside every .ewp, carrying the same file tree for
# the analysis tools and no include paths at all.
EWT = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<project>\n"
    "    <fileVersion>4</fileVersion>\n"
    "    <configuration>\n"
    "        <name>Proj</name>\n"
    "    </configuration>\n"
    "    <group>\n"
    "        <name>Drivers</name>\n"
    "        <file>\n"
    "            <name>$PROJ_DIR$\\..\\Drivers\\stm32g4xx_hal.c</name>\n"
    "        </file>\n"
    "    </group>\n"
    "</project>\n"
)


@pytest.fixture
def project(tmp_path):
    """
    Build an STM32 project on disk and return its path.

    Which IDE files appear is up to the test, since the point of most of them is
    checking one integration at a time. `newline` is there because CubeMX writes
    CRLF on Windows, and an integration that does not notice rewrites the line
    endings of the whole file to add one line to it.
    """

    def build(cmake=False, cubeide=False, keil=False, iar=False, hal_conf=None, ioc=None,
              newline="\n", iar_backup=False, keil_backup=False):
        root = tmp_path / "Proj"
        (root / "Core" / "Inc").mkdir(parents=True, exist_ok=True)
        (root / "Core" / "Src").mkdir(parents=True, exist_ok=True)
        (root / "Core" / "Src" / "main.c").write_text("/* main */\n", encoding="utf-8")

        def put(path, text):
            """Write a project file with the line ending this test asked for."""
            path.write_bytes(text.replace("\n", newline).encode("utf-8"))

        if cmake:
            put(
                root / "CMakeLists.txt",
                "cmake_minimum_required(VERSION 3.22)\n"
                "project(Proj C ASM)\n"
                "add_executable(${CMAKE_PROJECT_NAME} Core/Src/main.c)\n",
            )

        if cubeide:
            put(root / ".project", "<projectDescription/>\n")
            put(root / ".cproject", CPROJECT)

        if keil:
            mdk = root / "MDK"
            mdk.mkdir(exist_ok=True)
            put(mdk / "Proj.uvprojx", UVPROJX)

            if keil_backup:
                put(mdk / "Backup of Proj.uvprojx", UVPROJX)

        if iar:
            ewarm = root / "EWARM"
            ewarm.mkdir(exist_ok=True)
            put(ewarm / "Proj.ewp", EWP)
            put(ewarm / "Proj.ewt", EWT)
            put(ewarm / "Project.eww", EWW)

            if iar_backup:
                # What IAR leaves behind when it upgrades a project. It is a
                # valid .ewp, and its name sorts before the real one.
                put(ewarm / "Backup of Proj.ewp", EWP)

        if hal_conf is not None:
            (root / "Core" / "Inc" / "stm32f4xx_hal_conf.h").write_text(hal_conf, encoding="utf-8")

        if ioc is not None:
            (root / "Proj.ioc").write_text(ioc, encoding="utf-8")

        return root

    return build
