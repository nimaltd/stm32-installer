"""
Keil MDK, both uVision 5 and 6.

The two share the .uvprojx format, so one integration covers both. Keil does not
discover files on its own, so each source file has to be registered as well as
the include path.

Edited as text, not through an XML parser, so the rest of the file comes out of
this byte for byte identical.

The group is named after the library and nothing else, because that name is what
the user reads in the project tree all day. Knowing whether the library is
already there is therefore worked out from the file paths in the project rather
than from a marker in the name, which also means a group the user renamed is
still recognised.
"""

import re
from pathlib import Path, PurePosixPath

from .base import (
    ALREADY,
    CHANGED,
    MANUAL,
    Outcome,
    backup,
    forward_slashes,
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

NAME = "Keil MDK"

# <IncludePath>..\Core\Inc;..\Drivers\...</IncludePath>
INCLUDE_PATH = re.compile(r"(<IncludePath>)(.*?)(</IncludePath>)", re.DOTALL)

# <FilePath>..\Core\Src\main.c</FilePath>, read to see which slash is used and
# to tell whether the library's files are in the project already.
FILE_PATH = re.compile(r"<FilePath>(.*?)</FilePath>", re.DOTALL)

# The <Groups> container holding a target's file groups, and its body. There is
# one per target, and a project with a second target needs the library in both.
GROUPS = re.compile(r"(<Groups>)(.*?)(</Groups>)", re.DOTALL)


def detect(project_root):
    """
    The .uvprojx file, when this looks like a Keil project.

    Backups are skipped for the same reason as in the IAR integration: a copy
    the IDE left behind is a valid project file, and editing it changes nothing
    the user can see.
    """
    found = [p for p in sorted(Path(project_root).glob("**/*.uvprojx")) if not is_backup(p)]

    return found[0] if found else None


def _separator(text):
    """
    Which slash the project already writes its paths with.

    uVision writes backslashes into a path added through its own dialogs, and
    CubeMX generates forward slashes. Keil reads either, so the right one to use
    is simply whichever the file already uses.
    """
    paths = "".join(match.group(2) for match in INCLUDE_PATH.finditer(text))
    paths += "".join(match.group(1) for match in FILE_PATH.finditer(text))

    return "\\" if paths.count("\\") > paths.count("/") else "/"


def _file_paths(folder, sources, sep):
    """The <FilePath> values this would write, in the project's own slash."""
    base = folder.replace("/", sep)

    # The source's own folder as well: a mirror layout installs src/demo.c, and
    # joined on as it stood that gave ..\demo\src/demo.c.
    return [f"{base}{sep}{name.replace('/', sep)}" for name in sources]


def _file_entry(file_name, file_path, pad, step):
    """One <File> element, in the shape uVision writes them."""
    return [
        f"{pad}<File>",
        f"{pad}{step}<FileName>{file_name}</FileName>",
        f"{pad}{step}<FileType>1</FileType>",
        f"{pad}{step}<FilePath>{file_path}</FilePath>",
        f"{pad}</File>",
    ]


def _group(library_name, files, pad, step, newline):
    """A <Group> holding every source file of one library, as (name, path) pairs."""
    lines = [
        f"{pad}<Group>",
        f"{pad}{step}<GroupName>{library_name}</GroupName>",
        f"{pad}{step}<Files>",
    ]

    for file_name, file_path in files:
        lines += _file_entry(file_name, file_path, pad + step + step, step)

    lines += [f"{pad}{step}</Files>", f"{pad}</Group>"]

    return newline.join(lines)


def integrate(uvprojx, library, destination, project_root):
    """Register the library's sources and include path with a Keil project."""
    path = Path(uvprojx)
    # Paths inside a .uvprojx are relative to the folder holding it.
    folder = relative(destination, path.parent)

    try:
        text = read(path)
    except OSError as error:
        return Outcome(NAME, MANUAL, f"Could not read {path.name}: {error}", _manual_steps(folder))

    includes = list(INCLUDE_PATH.finditer(text))
    containers = list(GROUPS.finditer(text))

    if not includes or not containers:
        return Outcome(
            NAME,
            MANUAL,
            f"Could not find the file groups or include paths in {path.name}.",
            _manual_steps(folder),
        )

    newline = line_ending(text)
    sep = _separator(text)
    paths = _file_paths(folder, library.build_sources, sep)

    # The bare name comes from the manifest entry, which always uses forward
    # slashes, and not from the path above. Path(r"..\demo\demo.c").name is
    # demo.c on Windows, but the whole string on Linux and macOS, which do not
    # split at a backslash.
    files = list(zip((PurePosixPath(name).name for name in library.build_sources), paths))

    # A header only library has nothing to compile, so it gets an include path
    # and no group. An empty group would be added again on every run, since
    # there would be no file in the project to recognise it by.
    listed = {forward_slashes(match.group(1)) for match in FILE_PATH.finditer(text)}
    wanted = paths and not any(forward_slashes(p) in listed for p in paths)

    updated = text

    if wanted:
        # The group is appended after the target's own groups, which is where
        # uVision puts one added through Manage Project Items. Walking backwards
        # keeps each insertion from moving the offsets of the next.
        for container in reversed(containers):
            outer = indent_of(text, container.start())
            inner = inner_indent(container.group(2), outer)
            step = indent_step(outer, inner)
            at = insert_before(updated, container.start(3))

            block = _group(library.name, files, inner, step, newline)

            updated = updated[:at] + newline + block + updated[at:]

    directories = [d.replace("/", sep) for d in include_folders(library, folder.replace("/", sep))]

    def add_include(match):
        parts = [p for p in match.group(2).split(";") if p.strip()]
        present = {forward_slashes(p) for p in parts}
        parts += [d for d in directories if forward_slashes(d) not in present]

        return match.group(1) + ";".join(parts) + match.group(3)

    updated = INCLUDE_PATH.sub(add_include, updated)

    if updated == text:
        return Outcome(NAME, ALREADY, f"{path.name} already has {library.name}.")

    saved = backup(path)

    try:
        write(path, updated)
    except OSError as error:
        return Outcome(NAME, MANUAL, f"Could not write {path.name}: {error}",
                       _manual_steps(folder), saved)

    return Outcome(
        NAME,
        CHANGED,
        f"Added {library.name} to {path.name} in {len(containers)} target(s).",
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
