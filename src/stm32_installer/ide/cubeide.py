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

from .base import (
    ALREADY,
    CHANGED,
    MANUAL,
    Outcome,
    backup,
    include_folders,
    indent_of,
    inner_indent,
    insert_before,
    line_ending,
    read,
    relative,
    write,
)

NAME = "STM32CubeIDE"

# <option ... superClass="....compiler.option.includepaths" ...> and its body.
# The lookbehind keeps a self closing <option .../> out, since it has no body
# to add a path to. Options never nest, so the first </option> after the opening
# tag is always the matching one, even with self closing siblings in between.
INCLUDE_OPTION = re.compile(
    r'(<option[^>]*superClass="[^"]*compiler\.option\.includepaths"[^>]*(?<!/)>)'
    r"(.*?)"
    r"(</option>)",
    re.IGNORECASE | re.DOTALL,
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
        text = read(path)
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

    # Asked of each configuration separately rather than of the whole file. A
    # project that has the path on Debug but not on Release is one a whole file
    # check would call finished, and the missing half would only turn up as a
    # build that fails in one configuration and not the other.
    pending = [
        (match, [value for value in wanted if f'value="{value}"' not in match.group(2)])
        for match in matches
    ]
    pending = [(match, gaps) for match, gaps in pending if gaps]

    if not pending:
        return Outcome(NAME, ALREADY, f"{folder} is already on the include path.")

    saved = backup(path)

    newline = line_ending(text)
    updated = text

    # Walk backwards, so each insertion does not move the offsets of the next.
    for match, gaps in reversed(pending):
        outer = indent_of(text, match.start())
        inner = inner_indent(match.group(2), outer)
        at = insert_before(updated, match.start(3))

        added = "".join(
            f'{newline}{inner}<listOptionValue builtIn="false" value="{value}"/>'
            for value in gaps
        )

        # Appended after the paths that are already there, which is where
        # CubeIDE itself puts one added through the Properties dialog.
        updated = updated[:at] + added + updated[at:]

    try:
        write(path, updated)
    except OSError as error:
        return Outcome(NAME, MANUAL, f"Could not write .cproject: {error}",
                       _manual_steps(folder), saved)

    names = [value for value in wanted if any(value in gaps for _, gaps in pending)]

    return Outcome(
        NAME,
        CHANGED,
        f"Added {', '.join(names)} to the include paths of "
        f"{len(pending)} build configuration(s).",
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
