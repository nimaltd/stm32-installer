"""
IAR Embedded Workbench.

Like Keil, IAR registers every source file explicitly, so both the files and the
include path have to be added. Paths use the $PROJ_DIR$ variable, which keeps the
project movable.

Edited as text rather than through an XML parser, so everything this does not
touch survives byte for byte.
"""

import re
from pathlib import Path

from .base import ALREADY, CHANGED, MANUAL, Outcome, backup, relative

NAME = "IAR Embedded Workbench"

GROUP_NAME = "stm32-installer"

# The include path option, which repeats once per build configuration.
INCLUDE_OPTION = re.compile(
    r"(<option>\s*<name>CCIncludePath2</name>)(.*?)(</option>)",
    re.DOTALL,
)

# End of the project, where a new group can be appended.
PROJECT_CLOSE = re.compile(r"</project>\s*$")


def detect(project_root):
    """The .ewp file, when this looks like an IAR project."""
    matches = sorted(Path(project_root).glob("**/*.ewp"))

    return matches[0] if matches else None


def _group(library_name, folder, sources):
    """A <group> holding every source file of one library."""
    files = "".join(
        f"    <file>\n      <name>$PROJ_DIR$/{folder}/{name}</name>\n    </file>\n"
        for name in sources
    )

    return (
        "  <group>\n"
        f"    <name>{GROUP_NAME}: {library_name}</name>\n"
        f"{files}"
        "  </group>\n"
    )


def integrate(ewp, library, destination, project_root):
    """Register the library's sources and include path with an IAR project."""
    path = Path(ewp)
    # Paths inside a .ewp are written relative to the folder holding it.
    folder = relative(destination, path.parent)

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        return Outcome(NAME, MANUAL, f"Could not read {path.name}: {error}", _manual_steps(folder))

    marker = f"<name>{GROUP_NAME}: {library.name}</name>"

    if marker in text:
        return Outcome(NAME, ALREADY, f"{path.name} already has {library.name}.")

    includes = list(INCLUDE_OPTION.finditer(text))
    closing = PROJECT_CLOSE.search(text)

    if not includes or closing is None:
        return Outcome(
            NAME,
            MANUAL,
            f"Could not find the include paths or the end of {path.name}.",
            _manual_steps(folder),
        )

    saved = backup(path)

    state = f"<state>$PROJ_DIR$/{folder}</state>"

    def add_include(match):
        if state in match.group(2):
            return match.group(0)

        return match.group(1) + match.group(2).rstrip() + "\n      " + state + "\n    " + match.group(3)

    updated = INCLUDE_OPTION.sub(add_include, text)

    closing = PROJECT_CLOSE.search(updated)
    at = closing.start()
    updated = updated[:at] + _group(library.name, folder, library.build_sources) + updated[at:]

    try:
        path.write_text(updated, encoding="utf-8")
    except OSError as error:
        return Outcome(NAME, MANUAL, f"Could not write {path.name}: {error}",
                       _manual_steps(folder), saved)

    return Outcome(
        NAME,
        CHANGED,
        f"Added {library.name} to {path.name} as group '{GROUP_NAME}: {library.name}'.",
        steps=["Reopen the workspace in IAR so it reloads the file list."],
        backup=saved,
    )


def _manual_steps(folder):
    """What to click, when this could not do it safely."""
    return [
        "In IAR: right click the project, Add, Add Group, then add the",
        f".c files from {folder} to it.",
        "Then Project, Options, C/C++ Compiler, Preprocessor,",
        f"and add $PROJ_DIR$/{folder} to the include directories.",
    ]
