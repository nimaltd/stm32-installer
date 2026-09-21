"""
STM32CubeIDE, which is Eclipse underneath.

Two things have to be told to the project: where the header is, and that the
folder holds sources worth compiling. The second one is easy to miss, because
leaving it out looks like it worked. The header resolves, the editor stops
underlining things, and the build fails at link time on every symbol in the
library.

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

# The list of folders one build configuration compiles, and its body.
SOURCE_ENTRIES = re.compile(r"(<sourceEntries>)(.*?)(</sourceEntries>)", re.DOTALL)

# One <entry .../> inside it. The attributes are read separately rather than
# matched in a fixed order, since nothing promises CDT writes them the same way
# twice.
ENTRY = re.compile(r"<entry\b[^>]*/>")
ATTRIBUTE = re.compile(r'(\w+)="([^"]*)"')


def detect(project_root):
    """The .cproject file, when this looks like a CubeIDE project."""
    root = Path(project_root)
    cproject = root / ".cproject"

    if cproject.is_file() and (root / ".project").is_file():
        return cproject

    return None


def _source_paths(body):
    """The folder names a <sourceEntries> body lists as source."""
    names = []

    for element in ENTRY.findall(body):
        attributes = dict(ATTRIBUTE.findall(element))

        if attributes.get("kind") == "sourcePath":
            names.append(attributes.get("name", ""))

    return names


def _add_include_paths(text, wanted, newline):
    """Put the library on the include path of every build configuration."""
    updated = text

    # Walk backwards, so each insertion does not move the offsets of the next.
    for match in reversed(list(INCLUDE_OPTION.finditer(text))):
        # Asked of each configuration separately rather than of the whole file.
        # A project that has the path on Debug but not on Release is one a whole
        # file check would call finished, and the missing half would only turn
        # up as a build that fails in one configuration and not the other.
        gaps = [value for value in wanted if f'value="{value}"' not in match.group(2)]

        if not gaps:
            continue

        outer = indent_of(text, match.start())
        inner = inner_indent(match.group(2), outer)
        at = insert_before(updated, match.start(3))

        # Appended after the paths that are already there, which is where
        # CubeIDE itself puts one added through the Properties dialog.
        updated = updated[:at] + "".join(
            f'{newline}{inner}<listOptionValue builtIn="false" value="{value}"/>'
            for value in gaps
        ) + updated[at:]

    return updated


def _add_source_folder(text, folder, newline):
    """
    Register the library folder as one the project compiles.

    A <sourceEntries> block that names folders is the list of what gets built,
    and a folder missing from it is compiled by nobody.

    A block that is empty, or that carries a root entry with name="", already
    means the whole project is source. Adding a named entry to one of those
    would turn "build everything" into "build only this folder" and break the
    user's project rather than fix it, so they are left exactly as they are.
    That guard is the reason this is safe to do without being able to test it
    against a real CubeIDE.
    """
    updated = text

    for match in reversed(list(SOURCE_ENTRIES.finditer(text))):
        names = _source_paths(match.group(2))

        if not names or "" in names or folder in names:
            continue

        outer = indent_of(text, match.start())
        inner = inner_indent(match.group(2), outer)
        at = insert_before(updated, match.start(3))

        entry = (
            f'{newline}{inner}<entry flags="VALUE_WORKSPACE_PATH|RESOLVED" '
            f'kind="sourcePath" name="{folder}"/>'
        )

        updated = updated[:at] + entry + updated[at:]

    return updated


def integrate(cproject, library, destination, project_root):
    """Add the library to the include path and the source folders."""
    path = Path(cproject)
    folder = relative(destination, project_root)

    # Include paths in .cproject are relative to the build folder, not the
    # project root, which is why CubeIDE's own entries read ../Core/Inc. Source
    # folders are relative to the project, so the two are not the same string.
    wanted = [f"../{d}" for d in include_folders(library, folder)]

    try:
        text = read(path)
    except OSError as error:
        return Outcome(NAME, MANUAL, f"Could not read .cproject: {error}", _manual_steps(folder))

    if not INCLUDE_OPTION.search(text):
        return Outcome(
            NAME,
            MANUAL,
            "Could not find the include path settings in .cproject.",
            _manual_steps(folder),
        )

    newline = line_ending(text)

    updated = _add_include_paths(text, wanted, newline)
    with_sources = _add_source_folder(updated, folder, newline)
    registered = with_sources != updated
    updated = with_sources

    if updated == text:
        return Outcome(NAME, ALREADY, f"{folder} is already set up in .cproject.")

    saved = backup(path)

    try:
        write(path, updated)
    except OSError as error:
        return Outcome(NAME, MANUAL, f"Could not write .cproject: {error}",
                       _manual_steps(folder), saved)

    told = "include path and source folders" if registered else "include path"

    return Outcome(
        NAME,
        CHANGED,
        f"Added {folder} to the {told} in .cproject.",
        steps=["Refresh the project in CubeIDE (F5) so it picks up the new files."],
        backup=saved,
    )


def _manual_steps(folder):
    """What to click, when this could not do it safely."""
    return [
        "In STM32CubeIDE: right click the project, Properties,",
        "C/C++ Build, Settings, MCU GCC Compiler, Include paths,",
        f'then add "{folder}" as a workspace path.',
        f'If {folder} is greyed out in the project tree, right click it and',
        "choose Resource Configurations, Exclude from Build, and clear it.",
    ]
