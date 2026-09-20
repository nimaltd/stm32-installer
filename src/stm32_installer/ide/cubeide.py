"""
STM32CubeIDE, which is Eclipse underneath.

Only the include path needs adding. CubeIDE treats the project folder as a source
folder and compiles every .c under it on its own, which is also why the installer
strips the test folder out of a library before CubeIDE ever sees it.

The .cproject file is edited as text rather than through an XML parser. It opens
with a <?fileVersion?> processing instruction that ElementTree silently drops,
and a .cproject missing that line is a project that will not open.
"""

import re
from pathlib import Path

from .base import ALREADY, CHANGED, MANUAL, Outcome, backup, include_folders, relative

NAME = "STM32CubeIDE"

# <option ... superClass="....compiler.option.includepaths" ... > with children.
INCLUDE_OPTION = re.compile(
    r'(<option[^>]*superClass="[^"]*compiler\.option\.includepaths"[^>]*(?<!/)>)',
    re.IGNORECASE,
)


def detect(project_root):
    """The .cproject file, when this looks like a CubeIDE project."""
    root = Path(project_root)
    cproject = root / ".cproject"

    if cproject.is_file() and (root / ".project").is_file():
        return cproject

    return None


def integrate(cproject, library, destination, project_root):
    """Add the library folder to every build configuration's include paths."""
    path = Path(cproject)
    folder = relative(destination, project_root)

    # Include paths in .cproject are relative to the build folder, not the
    # project root, which is why CubeIDE's own entries read ../Core/Inc.
    wanted = [f"../{d}" for d in include_folders(library, folder)]

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        return Outcome(NAME, MANUAL, f"Could not read .cproject: {error}", _manual_steps(folder))

    matches = list(INCLUDE_OPTION.finditer(text))

    if not matches:
        return Outcome(
            NAME,
            MANUAL,
            "Could not find the include path settings in .cproject.",
            _manual_steps(folder),
        )

    missing = [value for value in wanted if f'value="{value}"' not in text]

    if not missing:
        return Outcome(NAME, ALREADY, f"{folder} is already on the include path.")

    saved = backup(path)

    added = "\n".join(f'<listOptionValue builtIn="false" value="{value}"/>' for value in missing)

    # Walk backwards, so each insertion does not move the offsets of the next.
    updated = text
    for match in reversed(matches):
        at = match.end()
        updated = updated[:at] + "\n" + added + updated[at:]

    try:
        path.write_text(updated, encoding="utf-8")
    except OSError as error:
        return Outcome(NAME, MANUAL, f"Could not write .cproject: {error}",
                       _manual_steps(folder), saved)

    return Outcome(
        NAME,
        CHANGED,
        f"Added {', '.join(missing)} to the include paths of "
        f"{len(matches)} build configuration(s).",
        steps=["Refresh the project in CubeIDE (F5) so it picks up the new files."],
        backup=saved,
    )


def _manual_steps(folder):
    """What to click, when this could not do it safely."""
    return [
        "In STM32CubeIDE: right click the project, Properties,",
        "C/C++ Build, Settings, MCU GCC Compiler, Include paths,",
        f'then add "{folder}" as a workspace path.',
    ]
