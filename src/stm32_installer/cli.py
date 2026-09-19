"""
The command line front end.

Two ways in, and they behave differently on purpose.

Local: the user downloaded a library repository into their project and runs its
install.py. The destination is already decided, it is that folder, so nothing is
asked. The repository scaffolding is stripped so the IDE does not try to compile
the test harness.

Online: the user ran the one line command from a README. Nothing is on disk yet,
so the folder is asked for, then only the files the manifest lists are fetched.

Either way the work happens in the same order: check the project against what the
library needs, copy the files, then register them with whatever IDE is found.
"""

import argparse
import sys
from pathlib import Path

from . import checks, console, download, ide, installer, manifest


def _header(library):
    """The block printed before anything is written."""
    lines = [console.banner(library.name, library.version, library.description)]
    lines.append(console.note(library.summary()))

    return "\n".join(lines)


def _ask_folder(default):
    """
    Ask where the library should go.

    Falls back to reading the console directly, because the online form pipes a
    script into a shell and stdin is already busy carrying that script.
    """
    prompt = console.strong(f"Folder to install into [{default}]: ")

    try:
        if sys.stdin is not None and sys.stdin.isatty():
            return input(prompt).strip() or default

        with open("/dev/tty", "r") as tty:
            print(prompt, end="", flush=True)
            return tty.readline().strip() or default
    except (OSError, EOFError, KeyboardInterrupt):
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

    for path in result.config_created:
        print(console.item("created", "yours to edit", _show(path, root), console.CYAN))

    for path in result.config_kept:
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


def _print_next(result, root, library):
    """The last word, which is the one people actually read."""
    folder = _show(result.destination, root)

    print()
    print(console.good(f'Done. #include "{library.name}.h" and you are away.'))

    if result.was_update:
        print(console.note("This was an update. Code replaced, your configuration kept."))

    if library.requires.libraries:
        print()
        print(console.warn("This library also needs: " + ", ".join(library.requires.libraries)))
        print(console.note(f"  Install each of them the same way."))

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
    """The part shared by both install routes."""
    _print_files(result, project_root)

    outcomes = ide.integrate(project_root, library, result.destination, only=only_ide)
    _print_ide(outcomes)
    _print_next(result, project_root, library)

    return 0


def _install_local(library_root, only_ide=None):
    """Flatten a repository that already sits inside the user's project."""
    library_root = Path(library_root).resolve()
    project_root = library_root.parent

    try:
        library = manifest.load(library_root)
    except manifest.ManifestError as error:
        # Installing removes library.yml, so the most likely reason it is
        # missing is that this folder has already been installed once.
        known = installer.installed_libraries(project_root)
        already = next(
            (n for n, d in known.items() if d.get("folder") == library_root.name), None
        )

        if already:
            print(console.warn(f"{already} is already installed in {library_root.name}."))
            print(console.note("  To update it, download the repository again and rerun this."))
            return 0

        print(console.bad(f"Error: {error}"), file=sys.stderr)
        return 2

    print(_header(library))
    _print_requirements(checks.check(library, project_root))

    try:
        result = installer.install_in_place(library)
    except installer.InstallError as error:
        print(console.bad(f"Error: {error}"), file=sys.stderr)
        return 2

    return _finish(library, result, project_root, only_ide)


def _install_online(source, ref, folder, project_root, only_ide=None):
    """Download a library and install it into a folder the user chooses."""
    print(console.note(f"Fetching {source} ..."))

    try:
        staged = download.fetch(source, ref=ref)
    except download.DownloadError as error:
        print(console.bad(f"Error: {error}"), file=sys.stderr)
        return 2

    try:
        library = manifest.load(staged)

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
        download.cleanup(staged)

    return _finish(library, result, project_root, only_ide)


def main(argv=None, library_root=None):
    """Entry point. Returns a process exit code."""
    parser = argparse.ArgumentParser(
        prog="stm32-install",
        description="Install a NimaLTD library into an STM32 project.",
        epilog="Run this from the root of your STM32 project.",
    )
    parser.add_argument(
        "library",
        nargs="?",
        default=None,
        help='what to install, for example "fsm", "nimaltd/fsm", or a GitHub URL.',
    )
    parser.add_argument("--ref", default="master", help="branch or tag to fetch. Default master.")
    parser.add_argument("--dir", dest="folder", default=None, help="folder to install into.")
    parser.add_argument(
        "--project", default=None, help="root of your STM32 project. Defaults to this folder."
    )
    parser.add_argument(
        "--local", default=None, help="install from a library folder already on disk."
    )
    parser.add_argument(
        "--ide",
        default=None,
        choices=["cmake", "cubeide", "keil", "iar"],
        help="only register with this IDE. Default is every one found.",
    )

    args = parser.parse_args(argv)

    project_root = Path(args.project).resolve() if args.project else Path.cwd().resolve()

    # install.py inside a repository passes its own folder, which means the
    # library is already where it belongs and nothing needs to be asked.
    if library_root is not None:
        return _install_local(library_root, args.ide)

    if args.local:
        return _install_local(args.local, args.ide)

    if not args.library:
        parser.print_help()
        print(
            console.bad("\nError: say which library to install, for example: stm32-install fsm"),
            file=sys.stderr,
        )
        return 2

    return _install_online(args.library, args.ref, args.folder, project_root, args.ide)


if __name__ == "__main__":
    sys.exit(main())
