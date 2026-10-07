"""
Copying a library into a user's STM32 project.

Three rules shape everything here.

The library's files are replaced on every install, so an update actually
updates, and a library the user broke by accident is put right.

What the user wrote between USER CODE BEGIN and USER CODE END survives that,
carried into the new file in the section of the same name, the way STM32CubeMX
keeps the user's code when it generates again. See usercode.py.

Files listed under once are copied once and then belong to the user, for the
libraries that still list any. Those predate the USER CODE sections.
"""

import json
import os
import shutil
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import usercode
from .ide.base import backup
from .manifest import DEFINE

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
    "installer.yml",
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
        # An update only: (from, to) for each of the user's files carried to
        # where the new version wants it, and the library's own files from the
        # last install that the new version no longer ships.
        self.moved = []
        self.dropped = []
        # An update only: (from, to, [section names]) for each library file the
        # new version puts in another folder, and the USER CODE sections that
        # went with it, none for a file that had none.
        self.carried = []
        # An update only: defines the last install of this library put in the
        # project and this version no longer asks for, so the IDE files can let
        # go of them. Only ever ones this library added.
        self.dropped_defines = []
        # (file, [section names]) for each file whose USER CODE sections were
        # carried into the new version.
        self.preserved = []
        # (file, backup, reason) for each copy put aside before something in it
        # was replaced or removed.
        self.backups = []
        # What each file written holds outside its USER CODE sections, kept in
        # the record so the next install can tell a hand edit there.
        self.fingerprints = {}

    @property
    def was_update(self):
        """True when the user's work was found and kept: a file, or a section in one."""
        return bool(self.kept) or bool(self.preserved)


def install_to(library, destination, project_root=None, record=True):
    """
    Copy a library's files into one folder.

    Where each file lands inside it is the library's layout: flat puts them all
    at the top, mirror keeps the repository's own folders.

    When the project already has this library in the same folder, this is an
    update, and the project is brought in step with the new version. The
    user's files move to wherever the new version puts them, rather than being
    created again beside the old ones. Files the last install wrote and the new
    version no longer ships are removed. Without that, a library that moved its
    code into src/ left the old copies behind, CubeIDE compiled both, and a
    fresh default config sat next to the header, silently winning over the
    user's own.

    Args:
        library: a Manifest, from manifest.load().
        destination: folder to write into. Created if missing.
        project_root: where the record of what was installed lives. Without
            it there is no record to read or write, so no update handling.
        record: write the record at the end. install_in_place() turns this off,
            since it records only after its cleanup has run.

    Returns:
        A Result listing every file written, created, kept, moved or dropped.
    """
    destination = Path(destination).resolve()

    if destination.exists() and not destination.is_dir():
        raise InstallError(f"{destination} is a file, so it cannot hold the library.")

    result = Result(library.name, library.version, destination)
    previous = _previous(project_root, library.name, destination) if project_root is not None else None

    # Every code file is checked before any is written. Markers that do not
    # pair are the library's mistake, and finding one half way would leave the
    # project with half of each version.
    for entry in library.code_files:
        try:
            usercode.parse((library.root / entry.source).read_bytes())
        except usercode.MarkerError as error:
            raise InstallError(
                f"{entry.source.as_posix()} in {library.name} has USER CODE markers that do not "
                f"pair, {error}. Nothing was installed."
            ) from error

    destination.mkdir(parents=True, exist_ok=True)

    # Code belongs to the library. Always replaced, so an update takes effect,
    # with the user's sections carried over.
    targets = {(destination / entry.destination).resolve() for entry in library.code_files}

    for entry in library.code_files:
        target = destination / entry.destination
        earlier = _moved_code(previous, project_root, target, targets)
        _write(library.root / entry.source, target, previous, project_root, result, earlier)

    # A kept file belongs to the user from the moment it first lands.
    for entry in library.once:
        target = destination / entry.destination
        template = library.root / entry.source
        earlier = _earlier_copy(previous, project_root, target)
        target.parent.mkdir(parents=True, exist_ok=True)

        # The user's copy from the last install, somewhere the new version no
        # longer looks. It moves, rather than a fresh default being created
        # beside the header, where it would be found first and quietly replace
        # the user's settings. It also takes over from a copy that is still
        # the untouched default: that is the template itself when installing
        # in place, or what an older installer created on an update.
        if earlier is not None and (not target.exists() or _same_content(target, template)):
            os.replace(earlier, target)
            result.moved.append((earlier, target))
            result.kept.append(target)
        elif target.exists():
            result.kept.append(target)
        else:
            shutil.copyfile(template, target)
            result.created.append(target)

    # The licence and the NOTICE ride along, because the licence says they must,
    # and anything else the manifest lists comes with them. Copied as they are:
    # they hold no USER CODE of the user's, and a README that shows the markers
    # in an example must not be read as having sections.
    for entry in library.present_extras():
        source = library.root / entry.source
        target = destination / entry.destination
        target.parent.mkdir(parents=True, exist_ok=True)

        if source.resolve() != target.resolve():
            shutil.copyfile(source, target)

        result.installed.append(target)

    if previous is not None:
        _drop_stale(previous, project_root, destination, result)
        result.dropped_defines = _dropped_defines(previous, library)

    if project_root is not None and record:
        _record(project_root, library, result)

    return result


def install_in_place(library, cleanup=True, project_root=None):
    """
    Turn a downloaded repository into a usable library folder, where it sits.

    Used when someone drops the whole repository into their project. The library
    files move up to the folder root and the repository scaffolding is removed,
    leaving a folder that holds only what the firmware needs.

    Args:
        library: a Manifest, from manifest.load().
        cleanup: remove the repository scaffolding. Off only for testing.
        project_root: where the record of the install goes. Defaults to the
            folder holding the library, which is the project only when the
            library sits at its top level rather than in, say, Libs/.

    Returns:
        A Result, with removed listing everything deleted.
    """
    root = Path(project_root) if project_root is not None else library.root.parent
    result = install_to(library, library.root, project_root=root, record=False)

    if cleanup:
        _remove_scaffolding(library, result)
        _remove_unchosen(library, result)

    _record(root, library, result)

    return result


def _write(source, target, previous, project_root, result, earlier=None):
    """
    Put one of the library's files in place, keeping the user's sections.

    The copy already there is put aside first when replacing it would lose
    something of the user's: a section the new version has no place for,
    sections whose markers no longer pair, or a hand edit outside them.

    earlier is where the last install put this file, when the new version puts
    it in another folder. Its sections are carried into the new place, the
    same as from a copy already there.
    """
    # A mirror layout, or an explicit "to", can put a file in a subfolder that
    # does not exist yet.
    target.parent.mkdir(parents=True, exist_ok=True)

    if source.resolve() == target.resolve():
        # Installing in place: the file already is the library's own.
        data = source.read_bytes()
    else:
        data = source.read_bytes()

        current = target if target.is_file() else earlier

        if current is not None:
            old = current.read_bytes()
            merged = usercode.merge(data, old)
            reasons = _losses(merged, old, data, current, previous, project_root)

            if reasons:
                result.backups.append((current, backup(current), "; ".join(reasons)))

            if merged.kept:
                result.preserved.append((target, merged.kept))

            if current != target:
                result.carried.append((current, target, merged.kept))

            data = merged.data

            # Left alone when nothing changed, so the build does not see a newer
            # file and compile it again for nothing.
            if (current != target) or (old != data):
                target.write_bytes(data)
        else:
            target.write_bytes(data)

    result.installed.append(target)
    result.fingerprints[target] = usercode.fingerprint(data)


def _moved_code(previous, project_root, target, targets):
    """
    Where the last install put a library file that this version puts elsewhere.

    Found by its name among the library's own files from the last install,
    littlefs/lfs_defines.h for littlefs/src/lfs_defines.h. Only when exactly one
    matches, it is still there, and this version installs nothing in its place.
    Anything else is not a move, and the file starts from what the library
    ships, as before.
    """
    if previous is None or project_root is None or target.exists():
        return None

    found = []

    for relative in previous.get("files") or []:
        old = Path(project_root) / relative

        try:
            resolved = old.resolve()
        except OSError:
            continue

        if old.name == target.name and resolved not in targets and old.is_file():
            found.append(old)

    return found[0] if len(found) == 1 else None


def _losses(merged, old, new, target, previous, project_root):
    """What replacing the copy already in the project would lose, in words."""
    reasons = []

    if merged.lost:
        reasons.append("the new version has no USER CODE " + ", ".join(merged.lost))

    if merged.broken:
        # Nothing in it could be told apart from the library's own text.
        reasons.append(f"its USER CODE markers do not pair ({merged.broken})")
        return reasons

    if previous is None or project_root is None:
        # No record of what was written here, so no way to tell a hand edit.
        return reasons

    relative = _relative(target, project_root)
    known = previous.get("fingerprints")

    if isinstance(known, dict) and relative in known:
        if usercode.fingerprint(old) != known[relative]:
            reasons.append("it was changed outside its USER CODE sections")
    elif relative in (previous.get("once") or []):
        # The user's own file until now, from a version that listed it under
        # once. Anything outside its sections may be theirs.
        if usercode.fingerprint(old) != usercode.fingerprint(new):
            reasons.append("it was yours to edit until now, and differs outside its USER CODE sections")

    return reasons


def _holds_user_work(path, previous, project_root):
    """Whether a file about to be removed has something of the user's in it."""
    try:
        data = path.read_bytes()
    except OSError:
        return False

    try:
        lines, sections = usercode.parse(data)
    except usercode.MarkerError:
        return True

    if any(b"".join(lines[first:last]).strip() for first, last in sections.values()):
        return True

    known = previous.get("fingerprints")
    relative = _relative(path, project_root)

    return isinstance(known, dict) and relative in known and usercode.fingerprint(data) != known[relative]


def _previous(project_root, name, destination):
    """
    The record of this library's last install, when it went into this folder.

    Installed somewhere else, it is a separate copy, and nothing of it is moved
    or removed from here.
    """
    entry = installed_libraries(project_root).get(name)

    if not isinstance(entry, dict) or not isinstance(entry.get("folder"), str):
        return None

    try:
        same = (Path(project_root) / entry["folder"]).resolve() == Path(destination).resolve()
    except OSError:
        return None

    return entry if same else None


def _earlier_copy(previous, project_root, target):
    """
    Where the last install put the user's copy of this file, if that is
    somewhere else and it is still there.
    """
    if previous is None:
        return None

    for relative in previous.get("once") or []:
        earlier = Path(project_root) / relative

        if earlier.name == target.name and earlier.resolve() != target.resolve() and earlier.is_file():
            return earlier

    return None


def _same_content(path, other):
    """Whether two files hold the same bytes. The same file counts, of course."""
    try:
        return path.resolve() == other.resolve() or path.read_bytes() == other.read_bytes()
    except OSError:
        return False


def _drop_stale(previous, project_root, destination, result):
    """
    Remove the library's own files that the last install wrote and this one did not.

    Only files the record lists as the library's, and only inside its folder.
    The user's files are recorded apart from those, and anything the user added
    was never recorded at all, so neither can end up here.
    """
    current = {p.resolve() for p in result.installed + result.created + result.kept}
    carried = {old.resolve() for old, _, _ in result.carried}

    for relative in previous.get("files") or []:
        old = Path(project_root) / relative

        try:
            resolved = old.resolve()
        except OSError:
            continue

        if resolved in current or not _within(resolved, destination) or not old.is_file():
            continue

        # Removed all the same, since a stale copy can be compiled beside the
        # new one, but not before anything of the user's in it is put aside.
        # A file whose sections went to its new place holds nothing more of the
        # user's. Anything it held outside them was put aside as it went.
        if resolved not in carried and _holds_user_work(old, previous, project_root):
            try:
                result.backups.append((old, backup(old), "no longer part of the library, and it held your changes"))
            except OSError:
                continue

        try:
            _unlink(old)
        except OSError:
            # A file the IDE holds open stays. Better than failing the update,
            # and it is not reported as removed.
            continue

        result.dropped.append(old)
        _prune(old.parent, destination)


def _dropped_defines(previous, library):
    """
    The defines the last install of this library asked for and this one does not.

    Read from the record, which is a file in the user's project anyone can
    edit, so an entry is checked as strictly as one from a manifest before it
    is used to find text to take out of a project file.
    """
    recorded = previous.get("defines")

    if not isinstance(recorded, list):
        return []

    return [
        define for define in recorded
        if isinstance(define, str) and DEFINE.match(define) and define not in library.defines
    ]


def _within(path, root):
    """Whether path is inside root, not root itself. 3.8 has no is_relative_to."""
    try:
        Path(path).relative_to(root)
    except ValueError:
        return False

    return Path(path) != Path(root)


def _prune(folder, stop):
    """Remove folders left empty, up to but not including stop."""
    folder = Path(folder)

    while _within(folder, stop):
        try:
            folder.rmdir()
        except OSError:
            break

        folder = folder.parent


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


def _remove_unchosen(library, result):
    """
    Delete the files of the options not taken, from a library installed in place.

    They came with the repository, and left there, STM32CubeIDE would compile
    them with everything else under the project: spif's littlefs port without
    littlefs, and a build that fails on a header nobody asked for.
    """
    for name, option in library.options.items():
        if name in library.chosen:
            continue

        for entry in option.code_files:
            target = library.root / entry.source

            if not target.is_file():
                continue

            try:
                _unlink(target)
            except OSError as error:
                result.removed.append(f"{entry.source.as_posix()} (could not remove: {error.strerror or error})")
                continue

            result.removed.append(entry.source.as_posix())
            _prune(target.parent, library.root)


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
        "fingerprints": {
            _relative(p, project_root): value for p, value in sorted(result.fingerprints.items())
        },
        "defines": list(library.defines),
        # Every option offered, and whether it was taken. One the record does
        # not name is new to this project, and is asked about.
        "options": {name: name in library.chosen for name in library.options},
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
