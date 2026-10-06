"""
Sections of a library file that belong to the user, marked the way STM32CubeMX
marks its own generated files:

    /* USER CODE BEGIN SEQ_CONFIGURATION */
    #define SEQ_MAX_TASKS  32
    /* USER CODE END SEQ_CONFIGURATION */

Every install copies the library's files afresh, so an update updates and a
library the user broke by accident is put right. What sits between a BEGIN and
its END is carried from the copy already in the project into the new file, in
the section of the same name.

Files are handled as bytes. Only the markers have to be ASCII, and the user's
text goes back exactly as it was, apart from its line endings, which follow
the new file so that one file never mixes the two.
"""

import hashlib
import re

# A marker is a comment alone on its line, the way CubeMX writes it, so a
# sentence or a README that only mentions one is not taken for one. The name
# is one word: Includes, PV, 0, SEQ_CONFIGURATION.
MARKER = re.compile(rb"[ \t]*(?:/\*|//|#)[ \t]*USER CODE (BEGIN|END)[ \t]+([^\s*]+)[ \t]*(?:\*/)?[ \t]*")


class MarkerError(Exception):
    """The markers in a file do not pair up, with the line that shows it."""


def parse(data):
    """
    Split a file into its lines and its sections.

    Args:
        data: the file's bytes.

    Returns:
        (lines, sections): the lines with their endings, and each section's
        name mapped to (first, last), so that its body is lines[first:last],
        the lines between its BEGIN and its END.

    Raises:
        MarkerError: a BEGIN with no END, an END with no BEGIN, a section that
            begins inside another, or one name used twice.
    """
    lines = data.splitlines(keepends=True)
    sections = {}
    open_name = None
    first = 0

    for number, line in enumerate(lines, start=1):
        marker = MARKER.fullmatch(line.rstrip(b"\r\n"))

        if marker is None:
            continue

        name = marker.group(2).decode("ascii", "replace")

        if marker.group(1) == b"BEGIN":

            if open_name is not None:
                raise MarkerError(f"line {number}: {name} begins inside {open_name}")

            if name in sections:
                raise MarkerError(f"line {number}: {name} is used twice")

            open_name, first = name, number

        else:
            if open_name is None:
                raise MarkerError(f"line {number}: END {name} has no BEGIN")

            if name != open_name:
                raise MarkerError(f"line {number}: END {name} closes {open_name}")

            sections[name] = (first, number - 1)
            open_name = None

    if open_name is not None:
        raise MarkerError(f"{open_name} has no END")

    return lines, sections


def line_ending(data):
    """The line ending a file uses: CRLF when it has any, otherwise LF."""
    return b"\r\n" if b"\r\n" in data else b"\n"


def _blank(lines):
    """Whether a section body holds nothing but white space."""
    return not b"".join(lines).strip()


class Merge:
    """A new file with the user's sections from the old one put back in."""

    def __init__(self, data, kept, lost, broken):
        self.data = data
        # Sections carried over with something in them.
        self.kept = kept
        # Sections of the old file with something in them that the new file
        # has no section of the same name for.
        self.lost = lost
        # Why the old file's sections could not be read, or None.
        self.broken = broken


def merge(new, old):
    """
    Put the user's sections from old into new.

    Args:
        new: the library's file, as the new version ships it.
        old: the copy already in the project.

    Returns:
        A Merge. An old file whose markers do not pair gives nothing to carry,
        and says why in broken. One with no markers at all is not broken: it
        simply has nothing to carry.

    Raises:
        MarkerError: from the new file, which is the library's mistake.
    """
    new_lines, new_sections = parse(new)

    try:
        old_lines, old_sections = parse(old)
        broken = None
    except MarkerError as error:
        old_lines, old_sections = [], {}
        broken = str(error)

    ending = line_ending(new)
    bodies = {}
    kept = []

    for name, (first, last) in new_sections.items():
        if name not in old_sections:
            continue

        old_first, old_last = old_sections[name]
        body = old_lines[old_first:old_last]
        bodies[first] = (last, [line.rstrip(b"\r\n") + ending for line in body])

        if not _blank(body):
            kept.append(name)

    out = []
    index = 0

    while index < len(new_lines):
        out.append(new_lines[index])

        if index + 1 in bodies:
            last, body = bodies[index + 1]
            out.extend(body)
            index = last
        else:
            index += 1

    lost = [
        name
        for name, (first, last) in old_sections.items()
        if name not in new_sections and not _blank(old_lines[first:last])
    ]

    return Merge(b"".join(out), kept, lost, broken)


def fingerprint(data):
    """
    What a file holds outside its sections, as a short hash.

    The installer keeps this for every file it writes. A copy that no longer
    matches it was changed by hand somewhere the next install will replace.
    Line endings do not count, since git and editors change those on their own.
    """
    try:
        lines, sections = parse(data)
    except MarkerError:
        lines, sections = data.splitlines(keepends=True), {}

    inside = set()

    for first, last in sections.values():
        inside.update(range(first, last))

    outside = b"\n".join(line.rstrip(b"\r\n") for i, line in enumerate(lines) if i not in inside)

    return hashlib.sha256(outside).hexdigest()[:16]
