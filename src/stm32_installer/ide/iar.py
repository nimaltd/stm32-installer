"""
IAR Embedded Workbench.

Like Keil, IAR registers every source file explicitly, so both the files and the
include path have to be added. Paths use the $PROJ_DIR$ variable, which keeps the
project movable.

Edited as text rather than through an XML parser, so everything this does not
touch survives byte for byte.

The group is named after the library and nothing else, because that name is what
the user reads in the project tree. Whether the library is already there is read
off the file paths instead of a marker in the name, so a group the user renamed
is still recognised.

Three things about the real files are easy to get wrong, and all three were:

- IAR leaves a "Backup of <name>.ewp" next to the project when it upgrades one,
  and that copy is a valid .ewp that sorts before the original. The workspace
  file says which project is the real one, so it is asked first.
- CubeMX mixes the two slashes inside one file, forward in the include paths and
  back in the file list, so which one to write is a question per section rather
  than per file.
- Groups nest, so a <group>...</group> regex closes on a child's tag rather than
  its own. Nothing here tries to match a whole group.
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
    indent_step,
    inner_indent,
    insert_before,
    is_backup,
    line_ending,
    read,
    relative,
    write,
)

NAME = "IAR Embedded Workbench"

# The include path option, which repeats once per build configuration.
INCLUDE_OPTION = re.compile(
    r"(<option>\s*<name>CCIncludePath2</name>)(.*?)(</option>)",
    re.DOTALL,
)

# A source file already in the project, read to see which slash is used and to
# tell whether the library's files are in the project already.
FILE_PATH = re.compile(r"<file>\s*<name>([^<]*)</name>", re.DOTALL)

# A group and the <name> line under it. That pair gives both the indentation of
# a group and the size of one step, without matching a whole group, which
# nesting makes impossible with a regex.
GROUP_INDENT = re.compile(r"^([ \t]*)<group>[ \t]*\r?\n([ \t]*)<name>", re.MULTILINE)

# <path>$WS_DIR$\Name.ewp</path>, the project a workspace points at.
WORKSPACE_PROJECT = re.compile(r"<path>\s*\$WS_DIR\$[\\/]([^<]+?)\s*</path>")

# End of the project, where a new group can be appended.
PROJECT_CLOSE = re.compile(r"</project>\s*$")


def _named_projects(workspace):
    """The .ewp files a workspace points at, resolved against its own folder."""
    try:
        text = read(workspace)
    except OSError:
        return []

    return [
        workspace.parent / match.group(1).replace("\\", "/")
        for match in WORKSPACE_PROJECT.finditer(text)
    ]


def detect(project_root):
    """
    The .ewp file, when this looks like an IAR project.

    The workspace comes first because it names the real project. Falling back to
    a plain search and taking the first hit is what put a library into "Backup
    of STM32G431CBU6.ewp" and reported success, while the project the user
    builds was never touched.
    """
    root = Path(project_root)

    for workspace in sorted(root.glob("**/*.eww")):
        for named in _named_projects(workspace):
            if named.is_file():
                return named

    found = [path for path in sorted(root.glob("**/*.ewp")) if not is_backup(path)]

    return found[0] if found else None


def _separator(sample):
    """
    Which slash a set of paths is written with.

    IAR takes either, and CubeMX uses both in one file: forward slashes in the
    include paths, backslashes in the file list. So this has to be asked of the
    section being edited, never of the whole file.
    """
    return "\\" if sample.count("$PROJ_DIR$\\") > sample.count("$PROJ_DIR$/") else "/"


def _file_names(text, folder, sources):
    """The <name> values this would write into the file list."""
    sep = _separator("".join(match.group(1) for match in FILE_PATH.finditer(text)))
    base = folder.replace("/", sep)

    return [f"$PROJ_DIR${sep}{base}{sep}{name}" for name in sources]


def _group(library_name, names, pad, step, newline):
    """A <group> holding every source file of one library."""
    lines = [
        f"{pad}<group>",
        f"{pad}{step}<name>{library_name}</name>",
    ]

    for name in names:
        lines += [
            f"{pad}{step}<file>",
            f"{pad}{step}{step}<name>{name}</name>",
            f"{pad}{step}</file>",
        ]

    lines.append(f"{pad}</group>")

    return newline.join(lines)


def _with_group(text, library_name, folder, sources):
    """
    The text with the library's group appended, or unchanged when there is
    nothing to add.

    Used for the .ewp and again for the .ewt beside it, which carries the same
    file tree for the analysis tools and no include paths at all.
    """
    names = _file_names(text, folder, sources)

    # A header only library has nothing to compile, so it gets an include path
    # and no group. An empty group would be added again on every run, since
    # there would be no file in the project to recognise it by.
    if not names or any(f"<name>{name}</name>" in text for name in names):
        return text

    closing = PROJECT_CLOSE.search(text)

    if closing is None:
        return text

    levels = sorted(GROUP_INDENT.findall(text), key=lambda pair: len(pair[0]))

    # The shallowest pair, so the indentation of a top level group rather than
    # of one nested inside another.
    pad, step = (levels[0][0], indent_step(*levels[0])) if levels else ("  ", "  ")

    newline = line_ending(text)
    at = insert_before(text, closing.start())

    return text[:at] + newline + _group(library_name, names, pad, step, newline) + text[at:]


def integrate(ewp, library, destination, project_root):
    """Register the library's sources and include path with an IAR project."""
    path = Path(ewp)
    # Paths inside a .ewp are written relative to the folder holding it.
    folder = relative(destination, path.parent)

    try:
        text = read(path)
    except OSError as error:
        return Outcome(NAME, MANUAL, f"Could not read {path.name}: {error}", _manual_steps(folder))

    includes = list(INCLUDE_OPTION.finditer(text))

    if not includes or PROJECT_CLOSE.search(text) is None:
        return Outcome(
            NAME,
            MANUAL,
            f"Could not find the include paths or the end of {path.name}.",
            _manual_steps(folder),
        )

    newline = line_ending(text)
    include_sep = _separator("".join(match.group(2) for match in includes))

    def add_include(match):
        outer = indent_of(match.string, match.start())
        inner = inner_indent(match.group(2), outer)
        body = match.group(2)

        added = [
            f"{newline}{inner}<state>$PROJ_DIR${include_sep}{d.replace('/', include_sep)}</state>"
            for d in include_folders(library, folder)
            if f"<state>$PROJ_DIR${include_sep}{d.replace('/', include_sep)}</state>" not in body
        ]

        if not added:
            return match.group(0)

        return match.group(1) + body.rstrip() + "".join(added) + newline + outer + match.group(3)

    updated = _with_group(
        INCLUDE_OPTION.sub(add_include, text), library.name, folder, library.build_sources
    )

    if updated == text:
        return Outcome(NAME, ALREADY, f"{path.name} already has {library.name}.")

    saved = backup(path)

    try:
        write(path, updated)
    except OSError as error:
        return Outcome(NAME, MANUAL, f"Could not write {path.name}: {error}",
                       _manual_steps(folder), saved)

    steps = ["Reopen the workspace in IAR so it reloads the file list."]
    also = _sync_companion(path, library, folder)

    if also:
        steps.insert(0, also)

    return Outcome(
        NAME,
        CHANGED,
        f"Added {library.name} to {path.name}.",
        steps=steps,
        backup=saved,
    )


def _sync_companion(ewp, library, folder):
    """
    Keep the .ewt beside the project in step with it.

    IAR writes one next to every .ewp and mirrors the file tree into it for the
    analysis tools. The build reads the .ewp, so this is not what makes the
    library compile, but leaving the two disagreeing is a difference the IDE
    will silently undo later and nobody will understand why.

    Returns a line for the user when it could not be done, and None when there
    was nothing to do or it worked.
    """
    companion = Path(ewp).with_suffix(".ewt")

    if not companion.is_file():
        return None

    try:
        text = read(companion)
    except OSError:
        return f"Could not read {companion.name}. Only {Path(ewp).name} was updated."

    updated = _with_group(text, library.name, folder, library.build_sources)

    if updated == text:
        return None

    backup(companion)

    try:
        write(companion, updated)
    except OSError:
        return f"Could not write {companion.name}. Only {Path(ewp).name} was updated."

    return None


def _manual_steps(folder):
    """What to click, when this could not do it safely."""
    return [
        "In IAR: right click the project, Add, Add Group, then add the",
        f".c files from {folder} to it.",
        "Then Project, Options, C/C++ Compiler, Preprocessor,",
        f"and add $PROJ_DIR$/{folder} to the include directories.",
    ]
