"""
Keil MDK, both uVision 5 and 6.

The two share the .uvprojx format, so one integration covers both. Keil does not
discover files on its own, so each source file has to be registered as well as
the include path.

Edited as text, not through an XML parser, so the rest of the file comes out of
this byte for byte identical.
"""

import re
from pathlib import Path

from .base import ALREADY, CHANGED, MANUAL, Outcome, backup, include_folders, relative

NAME = "Keil MDK"

GROUP_NAME = "stm32-installer"

# <IncludePath>..\Core\Inc;..\Drivers\...</IncludePath>
INCLUDE_PATH = re.compile(r"(<IncludePath>)(.*?)(</IncludePath>)", re.DOTALL)

# The <Groups> container holding the project's file groups.
GROUPS_OPEN = re.compile(r"<Groups>")


def detect(project_root):
    """The .uvprojx file, when this looks like a Keil project."""
    matches = sorted(Path(project_root).glob("**/*.uvprojx"))

    return matches[0] if matches else None


def _file_entry(source_path):
    """One <File> element, in the shape uVision writes them."""
    name = Path(source_path).name
    windows_path = str(source_path).replace("/", "\\")

    return (
        "        <File>\n"
        f"          <FileName>{name}</FileName>\n"
        "          <FileType>1</FileType>\n"
        f"          <FilePath>{windows_path}</FilePath>\n"
        "        </File>\n"
    )


def _group(library_name, folder, sources):
    """A <Group> holding every source file of one library."""
    files = "".join(_file_entry(f"{folder}/{name}") for name in sources)

    return (
        "      <Group>\n"
        f"        <GroupName>{GROUP_NAME}: {library_name}</GroupName>\n"
        "        <Files>\n"
        f"{files}"
        "        </Files>\n"
        "      </Group>\n"
    )


def integrate(uvprojx, library, destination, project_root):
    """Register the library's sources and include path with a Keil project."""
    path = Path(uvprojx)
    # Paths inside a .uvprojx are relative to the folder holding it.
    folder = relative(destination, path.parent)

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        return Outcome(NAME, MANUAL, f"Could not read {path.name}: {error}", _manual_steps(folder))

    marker = f"<GroupName>{GROUP_NAME}: {library.name}</GroupName>"

    if marker in text:
        return Outcome(NAME, ALREADY, f"{path.name} already has {library.name}.")

    includes = list(INCLUDE_PATH.finditer(text))
    groups = GROUPS_OPEN.search(text)

    if not includes or groups is None:
        return Outcome(
            NAME,
            MANUAL,
            f"Could not find the file groups or include paths in {path.name}.",
            _manual_steps(folder),
        )

    saved = backup(path)
    updated = text

    # Insert the group first, since it sits later in the file than the include
    # paths in every .uvprojx seen so far. Doing it in this order would still be
    # wrong if that ever changed, so both edits are recomputed from scratch.
    at = GROUPS_OPEN.search(updated).end()
    updated = updated[:at] + "\n" + _group(library.name, folder, library.build_sources) + updated[at:]

    wanted = [d.replace("/", "\\") for d in include_folders(library, folder)]

    def add_include(match):
        parts = [p for p in match.group(2).split(";") if p.strip()]
        parts += [d for d in wanted if d not in parts]

        return match.group(1) + ";".join(parts) + match.group(3)

    updated = INCLUDE_PATH.sub(add_include, updated)

    try:
        path.write_text(updated, encoding="utf-8")
    except OSError as error:
        return Outcome(NAME, MANUAL, f"Could not write {path.name}: {error}",
                       _manual_steps(folder), saved)

    return Outcome(
        NAME,
        CHANGED,
        f"Added {library.name} to {path.name} as group '{GROUP_NAME}: {library.name}'.",
        steps=["Close and reopen the project in uVision so it reloads the file list."],
        backup=saved,
    )


def _manual_steps(folder):
    """What to click, when this could not do it safely."""
    windows_folder = folder.replace("/", "\\")

    return [
        "In uVision: right click the target, Manage Project Items,",
        f"add a group and add the .c files from {windows_folder} to it.",
        "Then Options for Target, C/C++, Include Paths,",
        f"and add {windows_folder}.",
    ]
