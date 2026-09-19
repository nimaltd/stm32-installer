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
        config=None,
        requires=None,
        extra_files=None,
        root=None,
    ):
        root = Path(root) if root else tmp_path / name
        root.mkdir(parents=True, exist_ok=True)

        if config is None:
            config = [{"from": "template/demo_config.h"}]

        written = {
            "template/demo_config.h": "#define DEMO_SIZE 8\n",
            "NOTICE": f"{name}\nCopyright 2026 Nima Askari (NimaLTD)\n",
        }
        written.update({h: f"/* {Path(h).name} */\n" for h in headers})
        written.update({s: f"/* {Path(s).name} */\n" for s in sources})
        written.update(extra_files or {})

        for relative, text in written.items():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")

        data = {
            "name": name,
            "version": version,
            "kind": kind,
            "files": {"headers": list(headers), "sources": list(sources)},
        }

        if config:
            data["config"] = config

        if requires:
            data["requires"] = requires

        (root / "library.yml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

        return root

    return build


@pytest.fixture
def project(tmp_path):
    """
    Build an STM32 project on disk and return its path.

    Which IDE files appear is up to the test, since the point of most of them is
    checking one integration at a time.
    """

    def build(cmake=False, cubeide=False, keil=False, iar=False, hal_conf=None, ioc=None):
        root = tmp_path / "Proj"
        (root / "Core" / "Inc").mkdir(parents=True, exist_ok=True)
        (root / "Core" / "Src").mkdir(parents=True, exist_ok=True)
        (root / "Core" / "Src" / "main.c").write_text("/* main */\n", encoding="utf-8")

        if cmake:
            (root / "CMakeLists.txt").write_text(
                "cmake_minimum_required(VERSION 3.22)\n"
                "project(Proj C ASM)\n"
                "add_executable(${CMAKE_PROJECT_NAME} Core/Src/main.c)\n",
                encoding="utf-8",
            )

        if cubeide:
            (root / ".project").write_text("<projectDescription/>\n", encoding="utf-8")
            (root / ".cproject").write_text(
                '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
                "<?fileVersion 4.0.0?><cproject>\n"
                '  <option id="a" superClass="x.c.compiler.option.includepaths" valueType="includePath">\n'
                '    <listOptionValue builtIn="false" value="../Core/Inc"/>\n'
                "  </option>\n"
                '  <option id="b" superClass="x.c.compiler.option.includepaths" valueType="includePath">\n'
                '    <listOptionValue builtIn="false" value="../Core/Inc"/>\n'
                "  </option>\n"
                "</cproject>\n",
                encoding="utf-8",
            )

        if keil:
            mdk = root / "MDK"
            mdk.mkdir(exist_ok=True)
            (mdk / "Proj.uvprojx").write_text(
                "<Project>\n  <Cads><VariousControls>\n"
                "    <IncludePath>..\\Core\\Inc</IncludePath>\n"
                "  </VariousControls></Cads>\n"
                "  <Groups>\n    <Group>\n      <GroupName>Application</GroupName>\n"
                "      <Files></Files>\n    </Group>\n  </Groups>\n</Project>\n",
                encoding="utf-8",
            )

        if iar:
            ewarm = root / "EWARM"
            ewarm.mkdir(exist_ok=True)
            (ewarm / "Proj.ewp").write_text(
                "<project>\n  <option>\n    <name>CCIncludePath2</name>\n"
                "    <state>$PROJ_DIR$/../Core/Inc</state>\n  </option>\n</project>\n",
                encoding="utf-8",
            )

        if hal_conf is not None:
            (root / "Core" / "Inc" / "stm32f4xx_hal_conf.h").write_text(hal_conf, encoding="utf-8")

        if ioc is not None:
            (root / "Proj.ioc").write_text(ioc, encoding="utf-8")

        return root

    return build
