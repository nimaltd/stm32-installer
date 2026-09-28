"""
A Makefile, the kind STM32CubeMX writes when the toolchain is set to Makefile.

CubeMX lists every C file in C_SOURCES, every assembler file in ASM_SOURCES and
every include folder in C_INCLUDES, one per line, each line but the last ending
in a backslash. The library's entries go at the end of those lists, in the same
form as the ones already there, and nothing else in the file is touched.

Edited as text, like every other project file here, so the rest of it comes
out byte for byte identical.

CubeMX can write this file again when it generates code, and anything added to
it by hand, or by this, is gone after that. The report says to run the
installer again if it happens, which puts the entries back.
"""

import re
from pathlib import Path, PurePosixPath

from .base import (
    ALREADY,
    CHANGED,
    MANUAL,
    Outcome,
    backup,
    compiled_names,
    include_folders,
    line_ending,
    read,
    relative,
    write,
)

NAME = "Makefile"

# The first line of a list, NAME = followed by whatever is on that line.
LIST_START = r"^{name}[ \t]*=[^\r\n]*$"

# Which list each kind of file belongs in. CubeMX has no C++ rules, so a C++
# file gets a manual step rather than a line the build would not know what to
# do with.
LISTS = {".c": "C_SOURCES", ".s": "ASM_SOURCES", ".asm": "ASM_SOURCES"}

RERUN = (
    "CubeMX may write this Makefile again when it generates code. "
    "Run the installer again if the library is gone from it."
)


def detect(project_root):
    """
    The Makefile at the project's root, when it is one CubeMX wrote.

    Recognised by its C_SOURCES list rather than by name alone, since plenty of
    projects have a Makefile of some other shape.
    """
    path = Path(project_root) / "Makefile"

    if not path.is_file():
        return None

    try:
        text = read(path)
    except OSError:
        return None

    return path if re.search(LIST_START.format(name="C_SOURCES"), text, re.MULTILINE) else None


def _span(lines, name):
    """
    The first and last line of a list, as indexes into lines, or None.

    A list runs on for as long as its lines end in a backslash.
    """
    pattern = re.compile(LIST_START.format(name=name))

    for start, line in enumerate(lines):
        if pattern.match(line.rstrip("\r\n")):
            end = start

            while lines[end].rstrip().endswith("\\") and end + 1 < len(lines):
                end += 1

            return start, end

    return None


def _entry(line):
    """The entry a list line holds, without its backslash, or "" for none."""
    return line.rstrip().rstrip("\\").strip()


def _key(entry):
    """An entry as it compares: forward slashes, no leading ./"""
    entry = entry.replace("\\", "/")

    return entry[2:] if entry.startswith("./") else entry


def _entries(lines, span):
    """(line index, entry) for each entry in a list, the first line's own included."""
    start, end = span
    found = []

    for index in range(start, end + 1):
        text = lines[index]

        if index == start:
            text = text.split("=", 1)[1]

        entry = _entry(text)

        if entry:
            found.append((index, entry))

    return found


def _append(lines, span, entries, newline):
    """
    Add entries at the end of a list, in the shape of the ones already there.

    The line that used to be last gains a backslash, and so does every new line
    but the new last one.
    """
    start, end = span
    existing = _entries(lines, span)
    pad = ""

    if existing and existing[-1][0] != start:
        last = lines[existing[-1][0]]
        pad = last[: len(last) - len(last.lstrip(" \t"))]

    ending = lines[end][len(lines[end].rstrip("\r\n")):] or newline
    lines[end] = lines[end].rstrip() + (" \\" if lines[end].rstrip() else "\\") + ending

    added = [f"{pad}{entry} \\{ending}" for entry in entries]
    added[-1] = f"{pad}{entries[-1]}{ending}"
    lines[end + 1:end + 1] = added


def _drop(lines, span, index):
    """
    Remove one entry line from a list.

    When it was the last, the line now last loses its backslash, or the list
    would run on into whatever follows it.
    """
    start, end = span
    del lines[index]

    if index == end and end - 1 >= start:
        before = lines[end - 1]
        ending = before[len(before.rstrip("\r\n")):]
        body = before.rstrip("\r\n").rstrip()

        if body.endswith("\\"):
            lines[end - 1] = body[:-1].rstrip() + ending


def _follow(lines, name, dropped, wanted):
    """
    Bring a list in step with an update, before anything is added to it.

    A dropped file whose name the new version still has, somewhere else, has
    its entry changed where it stands. One with nothing to replace it loses its
    line. Returns the entries of wanted that are still not in the list.
    """
    span = _span(lines, name)

    if span is None:
        return list(wanted)

    listed = {_key(entry): index for index, entry in _entries(lines, span)}
    missing = [entry for entry in wanted if _key(entry) not in listed]
    keys = {_key(entry) for entry in wanted}

    for old in dropped:
        key = _key(old)

        if key in keys or key not in listed:
            continue

        index = listed[key]
        leaf = PurePosixPath(key).name
        moved = next((entry for entry in missing if PurePosixPath(_key(entry)).name == leaf), None)

        if moved is not None:
            lines[index] = lines[index].replace(_entry(lines[index]), moved, 1)
            missing.remove(moved)
        else:
            _drop(lines, span, index)
            span = _span(lines, name)
            listed = {_key(entry): i for i, entry in _entries(lines, span)}

    return missing


def integrate(makefile, library, destination, project_root, dropped=()):
    """
    Add the library's sources and include folder to a CubeMX Makefile.

    dropped lists the library files an update has just removed, so their
    entries can follow the file to its new place or go.
    """
    path = Path(makefile)
    # CubeMX writes every path relative to the project root, forward slashed.
    folder = relative(destination, path.parent)

    try:
        text = read(path)
    except OSError as error:
        return Outcome(NAME, MANUAL, f"Could not read the Makefile: {error}", _manual_steps(folder))

    newline = line_ending(text)
    lines = text.splitlines(keepends=True)

    if _span(lines, "C_SOURCES") is None or _span(lines, "C_INCLUDES") is None:
        return Outcome(NAME, MANUAL, "Could not find C_SOURCES and C_INCLUDES in the Makefile.",
                       _manual_steps(folder))

    gone = [f"{folder}/{name}" for name in compiled_names(dropped, destination)]
    listed = {
        _key(entry)
        for name in set(LISTS.values())
        if _span(lines, name) is not None
        for _, entry in _entries(lines, _span(lines, name))
    }
    was_there = any(_key(entry) in listed for entry in gone + [f"{folder}/{n}" for n in library.build_sources])
    by_list = {}
    other = []

    for name in library.build_sources:
        target = LISTS.get(PurePosixPath(name).suffix.lower())

        if target is None:
            other.append(f"{folder}/{name}")
        else:
            by_list.setdefault(target, []).append(f"{folder}/{name}")

    for target in sorted(set(LISTS.values())):
        old = [entry for entry in gone if LISTS.get(PurePosixPath(entry).suffix.lower()) == target]
        missing = _follow(lines, target, old, by_list.get(target, []))
        span = _span(lines, target)

        if missing and span is not None:
            _append(lines, span, missing, newline)
        elif missing:
            other += missing

    includes = [f"-I{d}" for d in include_folders(library, folder)]
    missing = _follow(lines, "C_INCLUDES", [], includes)

    if missing:
        _append(lines, _span(lines, "C_INCLUDES"), missing, newline)

    updated = "".join(lines)
    steps = [f"Add {entry} to the build by hand. CubeMX's Makefile has no rule for it." for entry in other]

    if updated == text:
        return Outcome(NAME, ALREADY, f"The Makefile already has {library.name}.", steps)

    saved = backup(path)

    try:
        write(path, updated)
    except OSError as error:
        return Outcome(NAME, MANUAL, f"Could not write the Makefile: {error}", _manual_steps(folder), saved)

    return Outcome(
        NAME,
        CHANGED,
        f"Updated {library.name} in the Makefile." if was_there
        else f"Added {library.name} to C_SOURCES and C_INCLUDES in the Makefile.",
        steps=steps + [RERUN],
        backup=saved,
    )


def _manual_steps(folder):
    """What to edit, when this could not do it safely."""
    return [
        f"In the Makefile, add the .c files from {folder} to C_SOURCES,",
        f"and -I{folder} to C_INCLUDES.",
    ]
