"""
The command line front end.

One argument says what to install, and it can be any of these:

    stm32-installer nimaltd/example                    GitHub, by owner and name
    stm32-installer example                            GitHub, owner nimaltd
    stm32-installer https://github.com/nimaltd/example GitHub, by address
    stm32-installer D:/Downloads/example-master.zip    the zip GitHub hands out
    stm32-installer D:/Downloads/example-master        a folder anywhere on disk
    stm32-installer example                            a folder already in the project

A path that exists always wins over a name, so a folder called "example" in the
project is used as it is and never confused with the repository of that name.

Several can be given in one run, such as a library and the zip of a library it
needs. A library lists what it needs under requires.libraries. What is missing
or too old goes in first, from the command line or else from GitHub, and what
is already in the project at a version that will do is left alone.

Where the library comes from decides what happens to it:

- From GitHub, from a zip, or from a folder outside the project, the files the
  manifest lists are copied into a folder of the project, asked for or given with
  --dir. The source is never changed.
- A folder already inside the project becomes the library where it stands. The
  repository scaffolding is removed from it, because STM32CubeIDE compiles every
  .c under the project and a test harness brings a second main() with it.

Either way the work happens in the same order: check the project against what the
library needs, copy the files, then register them with whatever IDE is found.
"""

import argparse
import os
import re
import sys
from pathlib import Path, PurePosixPath

from . import __version__, checks, console, download, ide, installer, manifest

# A drive letter, as in D:/Downloads or C:\Users.
_DRIVE = re.compile(r"^[A-Za-z]:")


def _header(library):
    """The block printed before anything is written."""
    lines = [console.banner(library.name, library.version, library.description)]
    lines.append(console.note(library.summary()))

    return "\n".join(lines)


def _ask_folder(default, name=None):
    """
    Ask where a library should go, or take the default when nobody can answer.

    name is said in the question once more than one library may be installed in
    one run, so it is clear which one the folder is for.

    Piped into Python, the installer arrives on stdin, so stdin cannot also carry
    the answer. The console is read directly instead: /dev/tty on Linux and
    macOS, CONIN$ on Windows. That is only tried when the output is going to a
    screen. Otherwise nobody is there to read the question, and waiting for an
    answer would hang a script or a build server for ever.
    """
    what = f"{name} " if name else ""
    prompt = console.strong(f"Folder to install {what}into [{default}]: ")

    try:
        if sys.stdin is not None and sys.stdin.isatty():
            return input(prompt).strip() or default

        if sys.stdout is None or not sys.stdout.isatty():
            return default

        device = "CONIN$" if os.name == "nt" else "/dev/tty"

        with open(device, "r") as terminal:
            print(prompt, end="", flush=True)
            return terminal.readline().strip() or default
    except (OSError, EOFError):
        return default


def _print_requirements(findings):
    """What the library needs, and whether the project looks ready for it."""
    if not findings:
        return

    print()
    print(console.heading("Requirements"))

    marks = {
        checks.OK: ("ok", console.GREEN),
        checks.WARN: ("check", console.YELLOW),
        checks.INFO: ("note", console.GREY),
    }

    for finding in findings:
        mark, colour = marks.get(finding.level, ("note", None))
        print(console.item(mark, "", finding.message, colour))

        if finding.hint and finding.level != checks.OK:
            print(f"          {console.note(finding.hint)}")


def _print_files(result, root):
    """Every file written, created, or deliberately left alone."""
    print()
    print(console.heading("Files"))

    for path in result.installed:
        print(console.item("written", "", _show(path, root), console.GREEN))

    for path in result.created:
        print(console.item("created", "yours to edit", _show(path, root), console.CYAN))

    moved_to = {new for _, new in result.moved}

    for path in result.kept:
        if path not in moved_to:
            print(console.item("kept", "not overwritten", _show(path, root), console.YELLOW))

    for old, new in result.moved:
        print(console.item("moved", "yours, kept as it was",
                           f"{_show(old, root)} -> {_show(new, root)}", console.CYAN))

    for path in result.dropped:
        print(console.item("removed", "no longer part of the library", _show(path, root),
                           console.YELLOW))

    if result.removed:
        print()
        print(console.note("  Removed, since they are part of the repository, not the firmware:"))
        print(console.note("    " + ", ".join(sorted(result.removed))))


def _print_ide(outcomes):
    """What was done to the project files, and what is left for the user."""
    if not outcomes:
        print()
        print(console.warn("No IDE project was recognised here, so nothing was registered."))
        print(console.note("  Add the folder to your include paths and the .c files to your build."))
        return

    print()
    print(console.heading("Project"))

    for outcome in outcomes:
        if outcome.status == ide.CHANGED:
            print(console.item("updated", "", f"{console.strong(outcome.ide)}  {outcome.message}", console.GREEN))
        elif outcome.status == ide.ALREADY:
            print(console.item("ok", "", f"{console.strong(outcome.ide)}  {outcome.message}", console.GREEN))
        else:
            print(console.item("manual", "", f"{console.strong(outcome.ide)}  {outcome.message}", console.YELLOW))

        for step in outcome.steps:
            print(f"          {console.note(step)}")

        if outcome.backup:
            print(f"          {console.note('backup: ' + outcome.backup.name)}")


def _include_name(library):
    """
    What goes between the quotes of the #include for this library.

    The first header the manifest lists, relative to the include folder it sits
    in. Not the library's name with .h added: the sequencer library's header is
    seq.h, and telling people to include sequencer.h sends them looking for a
    file that does not exist.
    """
    if not library.headers:
        return None

    landed = PurePosixPath(library.headers[0].destination)

    for folder in sorted(library.include_dirs, key=len, reverse=True):
        if folder in (".", ""):
            continue

        try:
            return landed.relative_to(folder).as_posix()
        except ValueError:
            continue

    return landed.as_posix()


def _print_next(result, root, library):
    """The last word, which is the one people actually read."""
    folder = _show(result.destination, root)
    header = _include_name(library)

    print()

    if header:
        print(console.good(f'Done. #include "{header}" and you are away.'))
    else:
        print(console.good("Done."))

    if result.was_update:
        print(console.note("This was an update. Code replaced, your configuration kept."))

    for warning in getattr(library, "warnings", []):
        print(console.note(f"  manifest: {warning}"))

    return folder


def _show(path, root):
    """A path relative to the project when possible, so output stays readable."""
    try:
        return Path(path).relative_to(root).as_posix()
    except ValueError:
        return Path(path).as_posix()


def _finish(library, result, project_root, only_ide):
    """The part shared by every install route."""
    _print_files(result, project_root)

    outcomes = ide.integrate(project_root, library, result.destination, only=only_ide,
                             dropped=result.dropped)
    _print_ide(outcomes)
    _print_next(result, project_root, library)

    return 0


def _looks_like_path(text):
    """
    Whether the argument can only be a path, never a library name.

    A path that does not exist is then reported as missing, rather than sent to
    GitHub, where a mistyped D:/Downloads/example.zip would come back as a
    baffling "repository not found" for an owner called "D:".
    """
    return (
        text.lower().endswith(".zip")
        or "\\" in text
        or text.startswith((".", "/", "~"))
        or bool(_DRIVE.match(text))
        or (not text.startswith(("http://", "https://")) and text.count("/") > 1)
    )


def _kind(path):
    """
    What is on disk at path: "zip", "file", "folder", or None for nothing.

    Never raises. A string that only looks like a path, or holds a character
    Windows refuses in a file name, is simply not there.
    """
    try:
        if path.is_dir():
            return "folder"

        if path.is_file():
            return "zip" if path.suffix.lower() == ".zip" else "file"
    except OSError:
        pass

    return None


def _inside(path, root):
    """
    Whether path is strictly inside root.

    Written out rather than Path.is_relative_to, which only arrived in Python
    3.9, and this still runs on 3.8.
    """
    try:
        path.relative_to(root)
    except ValueError:
        return False

    return path != root


def _error(message):
    """An error, on stderr, where a script looks for it."""
    print(console.bad(f"Error: {message}"), file=sys.stderr)


class _Source:
    """
    A library on disk, ready to install, and how it gets into the project.

    in_place is a folder already inside the project, which becomes the library
    where it stands. staging is a temporary folder this run made, the download
    or the unpacked zip, which is removed once the run is over. project_root is
    set only when the project is not the one the run was given: an install.py
    from an older release runs inside the library, whose parent is the project.
    """

    def __init__(self, root, in_place=False, staging=None, project_root=None):
        self.root = root
        self.in_place = in_place
        self.staging = staging
        self.project_root = project_root
        self.library = None


class _Step:
    """One install, in the order the plan puts them."""

    def __init__(self, source, needed_by=None, dependency=None, installed=None):
        self.source = source
        self.needed_by = needed_by
        self.dependency = dependency
        self.installed = installed


class _PlanError(Exception):
    """A library that cannot be had. Raised before anything is installed."""


def _stage_folder(folder, project_root):
    """A library folder on disk: converted where it stands, or copied in."""
    folder = folder.resolve()
    root = download.find_root(folder) or folder

    # Run from inside the library folder itself, which is what an install.py from
    # an older release does. The folder is the library and its parent the project.
    if root == project_root:
        return _Source(root, in_place=True, project_root=root.parent)

    if _inside(root, project_root):
        return _Source(root, in_place=True)

    print(console.note(f"Reading {folder.as_posix()} ..."))

    return _Source(root)


def _stage(target, ref, project_root, local=False):
    """
    Get one library named on the command line onto disk.

    Returns a _Source, or None once the reason it could not be had is printed.
    """
    if not target.startswith(("http://", "https://")):
        path = Path(target).expanduser()
        kind = _kind(path)

        if kind == "zip":
            print(console.note(f"Reading {path.name} ..."))

            try:
                staging, root = download.unpack(path.resolve())
            except download.DownloadError as error:
                _error(error)
                return None

            return _Source(root, staging=staging)

        if kind == "folder":
            return _stage_folder(path, project_root)

        if kind == "file":
            _error(
                f"{target} is not a .zip. Give the zip GitHub offers under "
                "Code, Download ZIP, or the folder it unpacks to."
            )
            return None

        if local or _looks_like_path(target):
            _error(f"{target} does not exist.")
            return None

    print(console.note(f"Fetching {target} ..."))

    try:
        staged = download.fetch(target, ref=ref)
    except download.DownloadError as error:
        _error(error)
        return None

    return _Source(staged, staging=staged)


def _load(source, project_root):
    """
    Read a source's library.yml.

    Returns None when it was read, otherwise the exit code to stop with, the
    reason already printed.
    """
    try:
        source.library = manifest.load(source.root)
    except manifest.ManifestError as error:
        # Installing in place removes library.yml, so the most likely reason it
        # is missing there is that this folder has already been installed once.
        if source.in_place:
            root = source.project_root or project_root
            known = installer.installed_libraries(root)
            where = _show(source.root, root)
            already = next((n for n, d in known.items() if d.get("folder") == where), None)

            if already:
                print(console.warn(f"{already} is already installed in {where}."))
                print(console.note("  To update it, run this again with a fresh download."))
                return 0

        _error(error)
        return 2

    return None


def _fetch_dependency(dependency, needed_by, staged):
    """
    Download a library another one needs, from GitHub.

    Raises _PlanError when it cannot be had, saying how to get it without the
    internet, since a missing connection is the usual reason.
    """
    print(console.note(f"{needed_by} needs {dependency}. Fetching {dependency.source} ..."))

    try:
        root = download.fetch(dependency.source, ref="master")
    except download.DownloadError as error:
        raise _PlanError(
            f"{needed_by} needs {dependency}, which is not in this project, and it could "
            f"not be fetched: {error}\n"
            f"Without the internet, download {dependency.name} as well, and give both "
            f"zips on one line:\n"
            f"    stm32-installer {needed_by}-master.zip {dependency.name}-master.zip"
        ) from error

    staged.append(root)
    source = _Source(root, staging=root)

    try:
        source.library = manifest.load(root)
    except manifest.ManifestError as error:
        raise _PlanError(f"{dependency.name}, which {needed_by} needs: {error}") from error

    return source


def _plan(requested, project_root, staged):
    """
    Put the installs in order: every library after the libraries it needs.

    A library that is needed and already in the project at a version that will
    do is left alone, and nobody is asked anything about it. One that is missing
    or too old comes from a zip or folder given on the same command line, or
    else from GitHub. All of that is worked out, and fetched, before anything
    is installed, so a library that cannot be had stops the run with the
    project untouched.

    staged collects every temporary folder made on the way, for the caller to
    remove.
    """
    recorded = installer.installed_libraries(project_root)
    given = {source.library.name: source for source in requested}
    planned = {}
    steps = []

    def visit(source, chain):
        name = source.library.name

        for dependency in source.library.requires.libraries:
            if dependency.name in chain:
                circle = " -> ".join(chain + [dependency.name])
                raise _PlanError(f"These libraries need each other in a circle: {circle}")

            # Already sorted out for an earlier library: in the project, or on
            # its way in. It only has to be new enough for this one as well.
            if dependency.name in planned:
                if not dependency.satisfied_by(planned[dependency.name]):
                    raise _PlanError(
                        f"{name} needs {dependency}, but {dependency.name} "
                        f"{planned[dependency.name]} is the one this run has."
                    )
                continue

            have = recorded.get(dependency.name)
            have = have if isinstance(have, dict) else None
            have_version = have.get("version") if have else None

            # In the project and new enough: nothing to do, nothing to ask. A
            # copy given on the command line is installed anyway, as asked.
            if have and dependency.name not in given and dependency.satisfied_by(have_version):
                print(console.note(
                    f"{name} needs {dependency}. {dependency.name} {have_version} is "
                    "already in this project, kept."
                ))
                planned[dependency.name] = have_version
                continue

            other = given.get(dependency.name) or _fetch_dependency(dependency, name, staged)

            if not dependency.satisfied_by(other.library.version):
                raise _PlanError(
                    f"{name} needs {dependency}, and the newest {dependency.name} to be "
                    f"had is {other.library.version}."
                )

            # What it needs comes before it.
            visit(other, chain + [dependency.name])

            steps.append(_Step(other, needed_by=name, dependency=dependency, installed=have))
            planned[dependency.name] = other.library.version

    for source in requested:
        # Given on the command line, and already installed as what an earlier
        # one needs.
        if source.library.name in planned:
            continue

        visit(source, [source.library.name])
        steps.append(_Step(source))
        planned[source.library.name] = source.library.version

    return steps


def _default_folder(library, project_root):
    """
    The folder offered for a library: where it already is, or its name.

    Offering the name for a library installed somewhere else, such as Libs/x,
    used to put a second copy of it in ./x on an update.
    """
    recorded = installer.installed_libraries(project_root).get(library.name)

    if isinstance(recorded, dict) and recorded.get("folder"):
        return recorded["folder"]

    return library.name


def _install_step(step, project_root, folder, only_ide):
    """Install one library of the plan. Returns an exit code."""
    source = step.source
    library = source.library
    root = source.project_root or project_root

    if step.needed_by and step.installed:
        print()
        print(console.note(
            f"{step.needed_by} needs {step.dependency}, newer than the "
            f"{step.installed.get('version')} in this project. Updating {library.name} first."
        ))
    elif step.needed_by:
        print()
        print(console.note(
            f"{step.needed_by} needs {step.dependency}, which is not in this project. "
            f"Installing {library.name} first."
        ))

    print()
    print(_header(library))
    _print_requirements(checks.check(library, root))

    try:
        if source.in_place:
            result = installer.install_in_place(library, project_root=root)
        else:
            print()

            # A library being updated because another needs a newer one goes
            # where it already is, without a question: it is not new to the
            # user. Anything else is asked for, or given with --dir.
            if step.needed_by and step.installed and step.installed.get("folder"):
                chosen = step.installed["folder"]
            else:
                chosen = folder or _ask_folder(_default_folder(library, root), library.name)

            result = installer.install_to(library, root / chosen, project_root=root)
    except installer.InstallError as error:
        _error(error)
        return 2

    return _finish(library, result, root, only_ide)


def _run(args, parser, library_root):
    """Get every library onto disk, work out the order, then install them in it."""
    project_root = Path(args.project).resolve() if args.project else Path.cwd().resolve()

    # An install.py from an older release passes the folder it sits in.
    if library_root is not None:
        targets = [str(library_root)]
    else:
        targets = ([args.local] if args.local else []) + list(args.library or [])

    if not targets:
        parser.print_help()
        print(
            console.bad(
                "\nError: say what to install, for example: stm32-installer nimaltd/example"
            ),
            file=sys.stderr,
        )
        return 2

    if args.folder and len(targets) > 1:
        _error(
            "--dir names the folder for one library. Give one library with it, or "
            "leave it out and answer the question for each."
        )
        return 2

    staged = []

    try:
        requested = []

        for target in targets:
            source = _stage(target, args.ref, project_root, local=target == args.local)

            if source is None:
                return 2

            if source.staging is not None:
                staged.append(source.staging)

            if source.in_place and args.folder:
                where = _show(source.root, source.project_root or project_root)
                _error(
                    f"{where} is already in the project, so it becomes the library where "
                    "it is and --dir has nothing to do.\n"
                    "Rename the folder instead, or install from a copy outside the project."
                )
                return 2

            code = _load(source, project_root)

            if code is not None:
                return code

            requested.append(source)

        try:
            steps = _plan(requested, project_root, staged)
        except _PlanError as error:
            _error(error)
            return 2

        for step in steps:
            folder = args.folder if step.needed_by is None else None
            code = _install_step(step, project_root, folder, args.ide)

            if code != 0:
                return code

        return 0
    finally:
        for path in staged:
            download.cleanup(path)


def main(argv=None, library_root=None):
    """Entry point. Returns a process exit code."""
    parser = argparse.ArgumentParser(
        prog="stm32-installer",
        description="Install a NimaLTD library into an STM32 project.",
        epilog="Run this from the root of your STM32 project.",
    )
    parser.add_argument(
        "library",
        nargs="*",
        default=None,
        help='what to install: a name like "nimaltd/example", a GitHub URL, '
        "a downloaded .zip, or a folder. Give several to install them together, "
        "such as a library and the zip of one it needs.",
    )
    parser.add_argument(
        "--ref",
        default="master",
        help="branch, tag or commit to fetch for the libraries named here. Default master. "
        "A library one of them needs is always fetched from its master.",
    )
    parser.add_argument("--dir", dest="folder", default=None, help="folder to install into.")
    parser.add_argument(
        "--project", default=None, help="root of your STM32 project. Defaults to this folder."
    )
    # Before a folder could be given as the plain argument, it took this option.
    # Kept working for anyone who still types it, but no longer advertised.
    parser.add_argument("--local", default=None, help=argparse.SUPPRESS)
    parser.add_argument(
        "--ide",
        default=None,
        choices=["cmake", "cubeide", "keil", "iar", "makefile"],
        help="only register with this IDE. Default is every one found.",
    )
    # -V as well, because that is what pip and python answer to.
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="show which version of the installer this is, and do nothing else.",
    )

    args = parser.parse_args(argv)

    try:
        return _run(args, parser, library_root)
    except KeyboardInterrupt:
        # Ctrl+C at the folder question used to mean "take the default" and go
        # ahead with the install. It means stop.
        print(console.warn("\nCancelled."), file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
