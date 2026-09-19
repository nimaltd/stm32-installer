"""
CMake projects, which covers VS Code and the CMake output of recent CubeMX.

The library's sources and include path are added to the project's CMakeLists.txt
inside a marked block, so a second install replaces that block rather than
appending another copy of it.

The target name is the awkward part. CubeMX writes ${CMAKE_PROJECT_NAME} and most
hand written projects use something else entirely, so the target is discovered
from the file rather than assumed.
"""

import re
from pathlib import Path

from .base import ALREADY, CHANGED, MANUAL, MARK_CLOSE, MARK_OPEN, Outcome, backup, relative

NAME = "CMake"

# add_executable(my_app ...) or add_library(my_lib ...)
TARGET = re.compile(r"^\s*add_(?:executable|library)\s*\(\s*([^\s)]+)", re.MULTILINE)

# CubeMX generated CMake projects define the target through the project() name.
PROJECT = re.compile(r"^\s*project\s*\(\s*([^\s)]+)", re.MULTILINE)


def detect(project_root):
    """The project's CMakeLists.txt, when this looks like a CMake project."""
    candidate = Path(project_root) / "CMakeLists.txt"

    return candidate if candidate.is_file() else None


def _find_target(text):
    """
    The CMake target to attach the library to.

    Prefers an explicit add_executable, since that is the firmware itself. Falls
    back to ${CMAKE_PROJECT_NAME}, which is what the CubeMX template uses.
    """
    match = TARGET.search(text)

    if match:
        name = match.group(1)
        # The CubeMX template writes add_executable(${CMAKE_PROJECT_NAME}), and
        # passing that straight back through is exactly right.
        return name

    if PROJECT.search(text):
        return "${CMAKE_PROJECT_NAME}"

    return None


def _block(library_name, folder, sources):
    """The text this tool owns inside the user's CMakeLists.txt."""
    listed = "\n".join(f"    {folder}/{name}" for name in sources)

    return (
        f"{MARK_OPEN.format(name=library_name)}\n"
        f"# Added by stm32-installer. Edit the lines if you move the folder,\n"
        f"# or delete the whole block to remove the library from the build.\n"
        f"target_sources(@TARGET@ PRIVATE\n{listed}\n)\n"
        f"target_include_directories(@TARGET@ PRIVATE {folder})\n"
        f"{MARK_CLOSE.format(name=library_name)}"
    )


def integrate(cmakelists, library, destination, project_root):
    """Add the library to a CMake project, replacing any block from a previous install."""
    path = Path(cmakelists)
    folder = relative(destination, project_root)

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        return Outcome(NAME, MANUAL, f"Could not read {path.name}: {error}",
                       _manual_steps(folder, library))

    target = _find_target(text)

    if target is None:
        return Outcome(
            NAME,
            MANUAL,
            f"Could not find an add_executable or project call in {path.name}.",
            _manual_steps(folder, library),
        )

    block = _block(library.name, folder, library.build_sources).replace("@TARGET@", target)

    open_mark = MARK_OPEN.format(name=library.name)
    close_mark = MARK_CLOSE.format(name=library.name)

    if open_mark in text:
        start = text.index(open_mark)
        end = text.index(close_mark) + len(close_mark) if close_mark in text else None

        if end is None:
            return Outcome(
                NAME,
                MANUAL,
                f"{path.name} has a half written stm32-installer block. Fix it by hand first.",
                _manual_steps(folder, library),
            )

        if text[start:end] == block:
            return Outcome(NAME, ALREADY, f"{path.name} already has {library.name}.")

        saved = backup(path)
        updated = text[:start] + block + text[end:]
    else:
        saved = backup(path)
        updated = text.rstrip("\n") + "\n\n" + block + "\n"

    try:
        path.write_text(updated, encoding="utf-8")
    except OSError as error:
        return Outcome(NAME, MANUAL, f"Could not write {path.name}: {error}",
                       _manual_steps(folder, library), saved)

    return Outcome(
        NAME,
        CHANGED,
        f"Added {library.name} to {path.name}, target {target}.",
        backup=saved,
    )


def _manual_steps(folder, library):
    """What to paste in, when this could not do it safely."""
    listed = "\n".join(f"    {folder}/{name}" for name in library.build_sources)

    return [
        "Add this to your CMakeLists.txt, using your own target name:",
        f"target_sources(your_target PRIVATE\n{listed}\n)",
        f"target_include_directories(your_target PRIVATE {folder})",
    ]
