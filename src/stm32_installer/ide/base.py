"""
Shared pieces for the IDE integrations.

Every integration edits a file the user cannot afford to lose. A corrupted
.cproject or .uvprojx means a project that will not open, and the user will not
connect that to having run an installer. So three rules hold everywhere:

1. Back the file up before touching it.
2. Bail out rather than guess. An integration that does not recognise the file
   reports what to do by hand and changes nothing.
3. Be idempotent. Installing twice must not add anything twice.

A fourth rule covers how the edit reads afterwards. These files are written by
tools, but people do open them, and they land in version control where every
line of them is reviewed. So an added line copies the indentation and the line
ending of the lines around it, rather than carrying a shape of its own.
"""

import os
import re
import shutil
from datetime import datetime
from pathlib import Path

# Wraps what this tool adds to a text file, so it can be found again.
MARK_OPEN = "# >>> stm32-installer: {name} >>>"
MARK_CLOSE = "# <<< stm32-installer: {name} <<<"

CHANGED = "changed"
ALREADY = "already"
MANUAL = "manual"
SKIPPED = "skipped"


class Outcome:
    """What an integration did, and what the user still has to do themselves."""

    def __init__(self, ide, status, message, steps=None, backup=None):
        self.ide = ide
        self.status = status
        self.message = message
        self.steps = steps or []
        self.backup = backup

    @property
    def needs_user(self):
        return self.status == MANUAL

    def __repr__(self):
        return f"Outcome({self.ide}, {self.status})"


def backup(path):
    """
    Copy a file aside before editing it.

    Named with a timestamp rather than a plain .bak, so a second install does
    not overwrite the copy taken before the first one.
    """
    path = Path(path)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = path.with_suffix(path.suffix + f".{stamp}.bak")

    shutil.copyfile(path, target)

    return target


def include_folders(library, folder):
    """
    Every folder of a library that belongs on the include path.

    A flat layout gives just the library folder. A mirror layout, or a manifest
    that says so, can give several, such as fsm/inc alongside fsm/port.
    """
    return [folder if d == "." else f"{folder}/{d}" for d in library.include_dirs]


def relative(path, root):
    """
    A forward slash path from root to path, going up where it has to.

    Keil and IAR keep their project file in a subfolder such as MDK or EWARM,
    so the library sits above it and the answer has to start with "..".
    Path.relative_to cannot express that, which is why os.path.relpath is used.
    Falls back to an absolute path only when the two are on different drives.
    """
    try:
        return Path(os.path.relpath(Path(path).resolve(), Path(root).resolve())).as_posix()
    except ValueError:
        return Path(path).resolve().as_posix()


def is_backup(path):
    """
    Whether this file is a copy an IDE or this installer left lying around.

    IAR writes "Backup of <name>.ewp" beside the real project when it upgrades
    one, and that copy is a perfectly valid project file whose name sorts before
    the original. Picking it is the worst kind of failure: the tool reports
    success, names a file that looks right, and the project the user actually
    builds is never touched. It cost a real debugging session on a G431 board.
    """
    name = Path(path).name

    return name.startswith("Backup of ") or name.endswith(".bak")


def read(path):
    """
    The file's text, with its line endings exactly as they are on disk.

    Path.read_text turns CRLF into LF, and Path.write_text on Windows turns
    every LF back into CRLF. Between them they rewrite the line endings of a
    whole project file in order to add one line to it, so a one line change
    lands in the user's history as a diff of the entire file.
    """
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return handle.read()


def write(path, text):
    """Write the text back with its line endings untouched. See read()."""
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def line_ending(text):
    """
    The line ending the file already uses.

    Writing a bare line feed into a file that is CRLF throughout leaves one odd
    line behind, which then shows up in every diff of that project.
    """
    return "\r\n" if "\r\n" in text else "\n"


def indent_of(text, at):
    """The whitespace that starts the line holding this offset."""
    start = text.rfind("\n", 0, at) + 1
    line = text[start:at]

    return line[: len(line) - len(line.lstrip(" \t"))]


def inner_indent(body, outer):
    """
    How deep the children of an element sit.

    Copied from a child that is already there, so it comes out in whatever the
    tool that wrote the file uses, tabs in a .cproject and spaces elsewhere.
    Only an element with no children left to copy from has to be guessed at.

    Takes the element's body rather than the whole element, so the element's own
    line cannot be mistaken for the first child.
    """
    match = re.search(r"\n([ \t]+)\S", body)

    if match:
        return match.group(1)

    return outer + ("\t" if outer.endswith("\t") else "  ")


def indent_step(outer, inner):
    """One nesting level, read off as the difference between two of them."""
    return inner[len(outer):] or ("\t" if outer.endswith("\t") else "  ")


def insert_before(text, at):
    """
    Where a new line goes so that it lands above the element starting at `at`.

    A closing tag usually sits alone on its line, and the caller wants the new
    content above it rather than wedged between its indentation and the tag. So
    the answer is the start of the line ending that closes the previous line,
    which puts the new content at the end of that line instead. The start of it,
    not the line feed, because landing between the carriage return and the line
    feed of a CRLF file splits that ending in two and leaves the line above
    looking changed in the diff. When the tag shares its line with something
    else there is no such spot, and the offset is returned unchanged.
    """
    head = text.rfind("\n", 0, at) + 1

    if head == 0 or text[head:at].strip() != "":
        return at

    end = head - 1

    return end - 1 if end > 0 and text[end - 1] == "\r" else end
