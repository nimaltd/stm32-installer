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
    clash_steps,
    compiled_names,
    element_indent,
    forward_slashes,
    include_folders,
    indent_of,
    indent_step,
    inner_indent,
    insert_before,
    is_backup,
    line_ending,
    plan_defines,
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

# One <File> element as whole lines, with whatever per-file options uVision has
# stored inside it. Elements do not nest, so the first </File> is its own.
FILE_ELEMENT = re.compile(r"^[ \t]*<File>.*?</File>[ \t]*\r?\n", re.DOTALL | re.MULTILINE)

# The C compiler settings of one target. The defines go in its <Define>, beside
# USE_HAL_DRIVER, and never in the one under <Aads>, which is the assembler's.
CADS = re.compile(r"<Cads>.*?</Cads>", re.DOTALL)
DEFINE = re.compile(r"(<Define>)(.*?)(</Define>)", re.DOTALL)


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


def _entry_path(element):
    """The path a <File> element names, forward slashed, or None."""
    match = FILE_PATH.search(element)

    return forward_slashes(match.group(1)) if match else None


def _follow(text, dropped_paths, files):
    """
    Bring the entries of files an update moved or removed in step with it.

    An entry whose file moved keeps its place, its group and any per-file
    options uVision stored in it. Only its path changes. An entry whose file
    has nothing to replace it is removed. Returns the new text and the
    (name, path) pairs the project still does not name at all.
    """
    wanted = {forward_slashes(path) for _, path in files}
    listed = {forward_slashes(match.group(1)) for match in FILE_PATH.finditer(text)}
    missing = [(name, path) for name, path in files if forward_slashes(path) not in listed]

    for old in dropped_paths:
        key = forward_slashes(old)

        if key in wanted or key not in listed:
            continue

        name = PurePosixPath(key).name
        moved = next((pair for pair in missing if pair[0] == name), None)

        if moved is not None:
            text = FILE_PATH.sub(
                lambda m: f"<FilePath>{moved[1]}</FilePath>"
                if forward_slashes(m.group(1)) == key else m.group(0),
                text,
            )
            missing.remove(moved)
        else:
            text = FILE_ELEMENT.sub(lambda m: "" if _entry_path(m.group(0)) == key else m.group(0), text)

    return text, missing


def _add_beside(text, missing, library, newline):
    """
    Add files the library gained next to its entries, in every target.

    Right after its last entry, which puts them in the library's own group
    whatever the user has renamed it to, lined up with the entries around them.
    """
    for container in reversed(list(GROUPS.finditer(text))):
        last = None

        for entry in FILE_ELEMENT.finditer(text, container.start(2), container.end(2)):
            if _entry_path(entry.group(0)) in library:
                last = entry

        if last is None:
            continue

        pad, step = element_indent(last.group(0))
        block = "".join(
            line + newline for name, path in missing for line in _file_entry(name, path, pad, step)
        )
        text = text[:last.end()] + block + text[last.end():]

    return text


def _edit_defines(text, wanted, dropped):
    """
    Bring the C define list of every target in step with the library.

    uVision separates them with commas, as CubeMX writes them, or with spaces,
    and reads either. What is added uses whichever the list already has.

    Returns the new text, the defines left alone because the list already sets
    the same name to something else, and whether any target had a list at all.
    """
    clashes = []
    found_any = False
    pieces = []
    last = 0

    for block in CADS.finditer(text):
        match = DEFINE.search(text, block.start(), block.end())

        if match is None:
            continue

        found_any = True
        written = match.group(2)
        present = [part for part in re.split(r"[,\s]+", written) if part]
        remove, add, found = plan_defines(present, wanted, dropped)
        clashes += [pair for pair in found if pair not in clashes]

        if not remove and not add:
            continue

        sep = ", " if ", " in written else ("," if "," in written or " " not in written.strip() else " ")
        kept = [part for part in present if part not in remove]

        pieces.append(text[last:match.start(2)])
        pieces.append(sep.join(kept + add))
        last = match.end(2)

    pieces.append(text[last:])

    return "".join(pieces), clashes, found_any


def integrate(uvprojx, library, destination, project_root, dropped=(), dropped_defines=()):
    """
    Register the library's sources, include path and defines with a Keil project.

    dropped lists the library files an update has just removed, so the entries
    that named them can follow the file to its new place or go. dropped_defines
    are taken out of the define lists.
    """
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

    # An update first. Entries for files that moved follow them, and entries
    # for files that are gone are removed, so what is missing after this is
    # only what the project has never had.
    dropped_paths = _file_paths(folder, compiled_names(dropped, destination), sep)
    listed = {forward_slashes(match.group(1)) for match in FILE_PATH.finditer(text)}
    was_there = any(forward_slashes(p) in listed for p in paths + dropped_paths)
    updated, missing = _follow(text, dropped_paths, files)

    # A header only library has nothing to compile, so it gets an include path
    # and no group. An empty group would be added again on every run, since
    # there would be no file in the project to recognise it by.
    if files and len(missing) == len(files):
        # The group is appended after the target's own groups, which is where
        # uVision puts one added through Manage Project Items. Walking backwards
        # keeps each insertion from moving the offsets of the next.
        before = updated

        for container in reversed(list(GROUPS.finditer(before))):
            outer = indent_of(before, container.start())
            inner = inner_indent(container.group(2), outer)
            step = indent_step(outer, inner)
            at = insert_before(updated, container.start(3))

            block = _group(library.name, files, inner, step, newline)

            updated = updated[:at] + newline + block + updated[at:]
    elif missing:
        # The library is in the project and this version added files to it.
        updated = _add_beside(updated, missing, {forward_slashes(p) for _, p in files}, newline)

    directories = [d.replace("/", sep) for d in include_folders(library, folder.replace("/", sep))]

    def add_include(match):
        parts = [p for p in match.group(2).split(";") if p.strip()]
        present = {forward_slashes(p) for p in parts}
        parts += [d for d in directories if forward_slashes(d) not in present]

        return match.group(1) + ";".join(parts) + match.group(3)

    updated = INCLUDE_PATH.sub(add_include, updated)
    updated, clashes, has_list = _edit_defines(updated, library.defines, dropped_defines)
    steps = clash_steps(clashes, path.name)

    # Without a define list the library would build, but with its defaults
    # instead of the settings it reads through the define, and nothing would
    # say so. So it is said here.
    unplaced = bool(library.defines) and not has_list

    if unplaced:
        steps += _define_steps(library.defines)

    if updated == text and unplaced:
        return Outcome(NAME, MANUAL, f"{path.name} has {library.name}, but no define list to add to.", steps)

    if updated == text:
        return Outcome(NAME, ALREADY, f"{path.name} already has {library.name}.", steps)

    saved = backup(path)

    try:
        write(path, updated)
    except OSError as error:
        return Outcome(NAME, MANUAL, f"Could not write {path.name}: {error}",
                       _manual_steps(folder), saved)

    message = (
        f"Updated {library.name} in {path.name}." if was_there
        else f"Added {library.name} to {path.name} in {len(containers)} target(s)."
    )

    if unplaced:
        return Outcome(NAME, MANUAL, message[:-1] + ", but found no define list to add to.", steps, saved)

    return Outcome(
        NAME,
        CHANGED,
        message,
        steps=steps + ["Close and reopen the project in uVision so it reloads the file list."],
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


def _define_steps(defines):
    """What to click to add the library's defines by hand."""
    return [
        "In uVision: Options for Target, C/C++, Preprocessor Symbols, and add to Define,",
        "for every target:",
        "    " + ",".join(defines),
    ]
