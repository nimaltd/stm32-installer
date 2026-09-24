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


def _ask_folder(default):
    """
    Ask where the library should go, or take the default when nobody can answer.

    Piped into Python, the installer arrives on stdin, so stdin cannot also carry
    the answer. The console is read directly instead: /dev/tty on Linux and
    macOS, CONIN$ on Windows. That is only tried when the output is going to a
    screen. Otherwise nobody is there to read the question, and waiting for an
    answer would hang a script or a build server for ever.
    """
    prompt = console.strong(f"Folder to install into [{default}]: ")

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

    for path in result.kept:
        print(console.item("kept", "not overwritten", _show(path, root), console.YELLOW))

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

    if library.requires.libraries:
        print()
        print(console.warn("This library also needs: " + ", ".join(library.requires.libraries)))
        print(console.note("  Install each of them the same way."))

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

    outcomes = ide.integrate(project_root, library, result.destination, only=only_ide)
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


def _install_in_place(library_root, project_root, folder, only_ide):
    """Turn a library folder that already sits in the project into the library."""
    if folder:
        print(
            console.bad(
                f"Error: {_show(library_root, project_root)} is already in the project, "
                "so it becomes the library where it is and --dir has nothing to do.\n"
                "Rename the folder instead, or install from a copy outside the project."
            ),
            file=sys.stderr,
        )
        return 2

    try:
        library = manifest.load(library_root)
    except manifest.ManifestError as error:
        # Installing removes library.yml, so the most likely reason it is
        # missing is that this folder has already been installed once.
        known = installer.installed_libraries(project_root)
        where = _show(library_root, project_root)
        already = next((n for n, d in known.items() if d.get("folder") == where), None)

        if already:
            print(console.warn(f"{already} is already installed in {where}."))
            print(console.note("  To update it, run this again with a fresh download."))
            return 0

        print(console.bad(f"Error: {error}"), file=sys.stderr)
        return 2

    print(_header(library))
    _print_requirements(checks.check(library, project_root))

    try:
        result = installer.install_in_place(library, project_root=project_root)
    except installer.InstallError as error:
        print(console.bad(f"Error: {error}"), file=sys.stderr)
        return 2

    return _finish(library, result, project_root, only_ide)


def _install_copy(library_root, project_root, folder, only_ide, staging=None):
    """
    Copy a library from wherever it is into a folder of the project.

    staging is a temporary folder this call owns and removes when done: the
    download, or the unpacked zip. A folder the user pointed at is never passed
    as staging, so it is never touched.
    """
    try:
        library = manifest.load(library_root)

        print()
        print(_header(library))
        _print_requirements(checks.check(library, project_root))
        print()

        destination = project_root / (folder or _ask_folder(library.name))
        result = installer.install_to(library, destination, project_root=project_root)
    except (manifest.ManifestError, installer.InstallError) as error:
        print(console.bad(f"Error: {error}"), file=sys.stderr)
        return 2
    finally:
        if staging is not None:
            download.cleanup(staging)

    return _finish(library, result, project_root, only_ide)


def _install_folder(folder, project_root, dir_name, only_ide):
    """A library folder on disk: converted where it is, or copied in."""
    folder = folder.resolve()
    root = download.find_root(folder) or folder

    # Run from inside the library folder itself, which is what an install.py from
    # an older release does. The folder is the library and its parent the project.
    if root == project_root:
        return _install_in_place(root, root.parent, dir_name, only_ide)

    if _inside(root, project_root):
        return _install_in_place(root, project_root, dir_name, only_ide)

    print(console.note(f"Reading {folder.as_posix()} ..."))

    return _install_copy(root, project_root, dir_name, only_ide)


def _install_zip(archive, project_root, dir_name, only_ide):
    """The zip GitHub hands out, installed without being unpacked by hand."""
    print(console.note(f"Reading {archive.name} ..."))

    try:
        staging, root = download.unpack(archive)
    except download.DownloadError as error:
        print(console.bad(f"Error: {error}"), file=sys.stderr)
        return 2

    return _install_copy(root, project_root, dir_name, only_ide, staging=staging)


def _install_online(source, ref, dir_name, project_root, only_ide):
    """Download a library and copy it into the project."""
    print(console.note(f"Fetching {source} ..."))

    try:
        staged = download.fetch(source, ref=ref)
    except download.DownloadError as error:
        print(console.bad(f"Error: {error}"), file=sys.stderr)
        return 2

    return _install_copy(staged, project_root, dir_name, only_ide, staging=staged)


def _run(args, parser, library_root):
    """Route the arguments to the install that fits them."""
    project_root = Path(args.project).resolve() if args.project else Path.cwd().resolve()

    # An install.py from an older release passes the folder it sits in.
    if library_root is not None:
        return _install_folder(Path(library_root), project_root, args.folder, args.ide)

    target = args.local or args.library

    if not target:
        parser.print_help()
        print(
            console.bad(
                "\nError: say what to install, for example: stm32-installer nimaltd/example"
            ),
            file=sys.stderr,
        )
        return 2

    if not target.startswith(("http://", "https://")):
        local = Path(target).expanduser()
        kind = _kind(local)

        if kind == "zip":
            return _install_zip(local.resolve(), project_root, args.folder, args.ide)

        if kind == "folder":
            return _install_folder(local, project_root, args.folder, args.ide)

        if kind == "file":
            print(
                console.bad(
                    f"Error: {target} is not a .zip. Give the zip GitHub offers under "
                    "Code, Download ZIP, or the folder it unpacks to."
                ),
                file=sys.stderr,
            )
            return 2

        if args.local or _looks_like_path(target):
            print(console.bad(f"Error: {target} does not exist."), file=sys.stderr)
            return 2

    return _install_online(target, args.ref, args.folder, project_root, args.ide)


def main(argv=None, library_root=None):
    """Entry point. Returns a process exit code."""
    parser = argparse.ArgumentParser(
        prog="stm32-installer",
        description="Install a NimaLTD library into an STM32 project.",
        epilog="Run this from the root of your STM32 project.",
    )
    parser.add_argument(
        "library",
        nargs="?",
        default=None,
        help='what to install: a name like "nimaltd/example", a GitHub URL, '
        "a downloaded .zip, or a folder.",
    )
    parser.add_argument("--ref", default="master", help="branch, tag or commit to fetch. Default master.")
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
        choices=["cmake", "cubeide", "keil", "iar"],
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
