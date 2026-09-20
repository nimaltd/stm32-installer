"""
Copying a library into a user's STM32 project.

Two rules shape everything here.

Code files are replaced on every install, so an update actually updates.
Files listed under once are copied once and then belong to the user, so an
update never throws away what they changed. That is usually a configuration
header, but the rule is about ownership, not about what the file holds.
"""

import json
import os
import shutil
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path

RECORD_NAME = ".stm32-installer.json"

# What a library repository carries that an STM32 project must not.
#
# test/ matters most. STM32CubeIDE compiles every .c file under the project
# tree, so a test harness left in place brings a second main() into the build
# and the link fails with an error that tells the user nothing useful.
#
# This is a fixed list rather than "everything that is not a library file", so
# that anything the user put in the folder themselves survives.
#
# LICENSE.md and NOTICE are deliberately absent. The Apache licence requires both
# to travel with the code, and the NOTICE file is what carries the author's
# attribution into the user's product.
DEFAULT_CLEANUP = [
    ".git",
    ".github",
    ".clang-format",
    ".gitignore",
    "build",
    "test",
    "inc",
    "src",
    "template",
    "CMakeLists.txt",
    "CONTRIBUTING.md",
    "library.yml",
    "install.py",
]


class InstallError(Exception):
    """The install cannot proceed, with a reason worth showing the user."""


class Result:
    """What an install actually did, so the caller can report it honestly."""

    def __init__(self, name, version, destination):
        self.name = name
        self.version = version
        self.destination = Path(destination)
        self.installed = []
        self.created = []
        self.kept = []
        self.removed = []

    @property
    def was_update(self):
        """True when a kept file was already there and was left alone."""
        return bool(self.kept)


def install_to(library, destination, project_root=None):
    """
    Copy a library's files into one folder.

    Everything lands flat, so the user adds a single include path rather than
    one per subdirectory.

    Args:
        library: a Manifest, from manifest.load().
        destination: folder to write into. Created if missing.
        project_root: where to write the record of what was installed. Skipped
            when not given, which is what install_in_place() wants, since it
            records only after its cleanup has run.

    Returns:
        A Result listing every file written, created or deliberately kept.
    """
    destination = Path(destination).resolve()

    if destination.exists() and not destination.is_dir():
        raise InstallError(f"{destination} is a file, so it cannot hold the library.")

    result = Result(library.name, library.version, destination)

    destination.mkdir(parents=True, exist_ok=True)

    # Code belongs to the library. Always overwrite, so an update takes effect.
    for entry in library.code_files:
        source = library.root / entry.source
        target = destination / entry.destination

        # A mirror layout, or an explicit "to", can put a file in a subfolder
        # that does not exist yet.
        target.parent.mkdir(parents=True, exist_ok=True)

        if source.resolve() != target.resolve():
            shutil.copyfile(source, target)

        result.installed.append(target)

    # A kept file belongs to the user from the moment it first lands.
    for entry in library.once:
        target = destination / entry.destination
        target.parent.mkdir(parents=True, exist_ok=True)

        if target.exists():
            result.kept.append(target)
        else:
            shutil.copyfile(library.root / entry.source, target)
            result.created.append(target)

    # The licence and the NOTICE ride along, because the licence says they must,
    # and anything else the manifest lists comes with them.
    for entry in library.present_extras():
        source = library.root / entry.source
        target = destination / entry.destination
        target.parent.mkdir(parents=True, exist_ok=True)

        if source.resolve() != target.resolve():
            shutil.copyfile(source, target)

        result.installed.append(target)

    if project_root is not None:
        _record(project_root, library, result)

    return result


def install_in_place(library, cleanup=True):
    """
    Turn a downloaded repository into a usable library folder, where it sits.

    Used when someone drops the whole repository into their project. The library
    files move up to the folder root and the repository scaffolding is removed,
    leaving a folder that holds only what the firmware needs.

    Args:
        library: a Manifest, from manifest.load().
        cleanup: remove the repository scaffolding. Off only for testing.

    Returns:
        A Result, with removed listing everything deleted.
    """
    result = install_to(library, library.root)

    if cleanup:
        _remove_scaffolding(library, result)

    _record(library.root.parent, library, result)

    return result


def _remove_scaffolding(library, result):
    """
    Delete the repository-only paths, leaving anything the user added.

    What is kept is worked out from where the files actually landed, not from
    their names. A mirror layout leaves them in inc/ and src/, and those folders
    are on the cleanup list, so going by name alone would install four files and
    then delete all four.
    """
    keep = set()

    for path in result.installed + result.created + result.kept:
        try:
            landed = path.relative_to(library.root)
        except ValueError:
            continue

        # The top level name under the install folder, which is what the
        # cleanup list is written in terms of.
        if landed.parts:
            keep.add(landed.parts[0])

    for name in DEFAULT_CLEANUP:
        target = library.root / name

        if not target.exists() or name in keep:
            continue

        try:
            if target.is_dir():
                _rmtree(target)
            else:
                _unlink(target)
        except OSError as error:
            # A locked file is worth mentioning, never worth failing the install.
            result.removed.append(f"{name} (could not remove: {error.strerror or error})")
            continue

        result.removed.append(name)


def _force_writable(func, path, _error):
    """
    Retry a failed delete after clearing the read-only bit.

    Git marks everything under .git/objects read-only, and on Windows that stops
    a delete outright rather than being advisory as it is on Unix. Without this,
    removing a cloned repository always fails part way through.
    """
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        raise


def _rmtree(path):
    """Delete a folder, including read-only files. The keyword changed in 3.12."""
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_force_writable)
    else:
        shutil.rmtree(path, onerror=_force_writable)


def _unlink(path):
    """Delete a file, including a read-only one."""
    try:
        path.unlink()
    except PermissionError:
        os.chmod(path, stat.S_IWRITE)
        path.unlink()


def _record(project_root, library, result):
    """Note what was installed, so update and uninstall have something to work from."""
    project_root = Path(project_root)
    path = project_root / RECORD_NAME
    data = {"libraries": {}}

    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("libraries"), dict):
                data = loaded
        except (json.JSONDecodeError, OSError):
            # A damaged record should never block an install. It gets rewritten.
            pass

    data["libraries"][library.name] = {
        "version": library.version,
        "repository": library.repository,
        "folder": _relative(result.destination, project_root),
        "files": sorted(_relative(p, project_root) for p in result.installed),
        "once": sorted(_relative(p, project_root) for p in result.created + result.kept),
        "installed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    try:
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        # A read-only project root is unusual, but it must not fail a good install.
        pass


def _relative(path, root):
    """Path relative to root where possible, absolute where not, always posix style."""
    try:
        return Path(path).relative_to(root).as_posix()
    except ValueError:
        return Path(path).as_posix()


def installed_libraries(project_root):
    """Read back what this tool has installed into a project. Empty when nothing has."""
    path = Path(project_root) / RECORD_NAME

    if not path.is_file():
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

    libraries = data.get("libraries")

    return libraries if isinstance(libraries, dict) else {}
