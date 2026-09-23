"""
Reading and validating a library.yml manifest.

Every NimaLTD library repository carries one of these at its root. It answers
three questions: what the library is, what it needs from the project, and which
files make it up.

The "what it is" part matters more than it first appears. A library can itself
be an RTOS, so saying only what a library requires is not enough. A library
declares its kind, and declares what it provides, and another library's
requirement is then satisfied by whatever provides that thing.
"""

import re
from pathlib import Path, PurePosixPath

from . import yamlreader

MANIFEST_NAME = "library.yml"

# What a library is. Used for grouping and for satisfying requirements.
KINDS = (
    "driver",      # talks to a chip or a peripheral
    "middleware",  # sits between the application and a driver
    "rtos",        # is itself an operating system
    "protocol",    # implements a wire protocol
    "filesystem",  # stores files
    "utility",     # general help, no hardware of its own
    "bsp",         # board support, pin maps and wiring
)

# Finer grouping, used when listing libraries to a user.
CATEGORIES = (
    "sensor",
    "storage",
    "display",
    "communication",
    "wireless",
    "rtos",
    "timing",
    "power",
    "input",
    "math",
    "system",
)

# How a library relates to an operating system.
RTOS_CHOICES = (
    "none",        # bare metal, does not care
    "optional",    # works either way
    "any",         # needs some RTOS, does not mind which
    "freertos",
    "cmsis-os2",
    "threadx",
)


class ManifestError(Exception):
    """A manifest is missing, unreadable, or does not describe a usable library."""


# Where a library's version lives: the @version tag in its header's file comment.
_VERSION_TAG = re.compile(r"@version\s+(\S+)")

UPDATE_COMMAND = (
    "pip install --upgrade https://github.com/nimaltd/stm32-installer/archive/refs/heads/main.zip"
)


def _version_tuple(text):
    """(1, 2, 0) from "1.2.0", or None when it is not three whole numbers."""
    parts = str(text).strip().split(".")

    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return None

    return tuple(int(part) for part in parts)


def check_installer(data):
    """
    Refuse a manifest written for a newer installer than this one.

    Called before anything else in the file is read. A manifest that needs a
    newer installer may use something this one does not understand, and reading
    it wrongly without a word is worse than stopping with the way forward.

    Raises:
        ManifestError, naming the version needed and how to update.
    """
    from . import __version__

    requires = data.get("requires")

    if not isinstance(requires, dict) or requires.get("installer") is None:
        return

    wanted = _version_tuple(requires["installer"])

    if wanted is None:
        raise ManifestError(
            f"requires.installer is {requires['installer']!r}. Write it as three numbers, "
            "like 1.1.0. YAML reads an unquoted 1.10 as the decimal number 1.1."
        )

    have = _version_tuple(__version__) or (0, 0, 0)

    if wanted > have:
        needed = ".".join(str(part) for part in wanted)
        raise ManifestError(
            f"This library needs stm32-installer {needed} or newer, and this one is "
            f"{__version__}. Nothing was changed.\n"
            f"Update it with:\n    {UPDATE_COMMAND}"
        )


def _header_version(root, headers):
    """The @version tag in the first header's file comment, or None."""
    if not headers:
        return None

    try:
        with open(Path(root) / headers[0].source, encoding="utf-8", errors="replace") as handle:
            found = _VERSION_TAG.search(handle.read(4096))
    except OSError:
        return None

    return found.group(1) if found else None


# How files are laid out inside the folder they are installed into.
LAYOUTS = (
    "flat",    # every file at the top, so one include path covers the library
    "mirror",  # keep the repository's own folders, for a library too big to flatten
)


class OnceFile:
    """
    A file copied once and then left alone, because it belongs to the user.

    Usually a configuration header, but the rule is about ownership rather than
    content: a port layer someone fills in, or a table they tune, wants exactly
    the same treatment.
    """

    def __init__(self, source, destination):
        self.source = source
        self.destination = destination

    def __repr__(self):
        return f"OnceFile({self.source!r} -> {self.destination!r})"


class FileEntry:
    """One file, where it lives in the repository and where it lands."""

    def __init__(self, source, destination):
        self.source = Path(source)
        # Kept as posix text, because it ends up in CMake, Keil and IAR project
        # files, and every one of them is happy with forward slashes.
        self.destination = str(destination).replace("\\", "/")

    @property
    def folder(self):
        """The destination's folder, relative to the install folder. "." at the top."""
        parent = Path(self.destination).parent.as_posix()

        return "." if parent in ("", ".") else parent

    def __repr__(self):
        return f"FileEntry({self.source.as_posix()!r} -> {self.destination!r})"


def is_pattern(path):
    """Whether a manifest entry names more than one file."""
    return any(ch in str(path) for ch in "*?[")


def expand(root, entry, known=None):
    """
    Turn one manifest entry into the repository paths it names.

    An entry is a file, a folder, or a wildcard. A folder means every file
    beneath it, and a wildcard is matched the way a shell would. Results come
    back sorted, so a manifest produces the same install every time.

    Args:
        root: the repository root, used when matching against a local checkout.
        entry: the path, folder or pattern written in the manifest.
        known: every path in the repository, for matching without a checkout.
            The online install passes this, since it has no files on disk yet.

    Returns:
        A list of repository relative Paths, empty when nothing matched.
    """
    text = Path(entry).as_posix()

    if known is not None:
        if is_pattern(text):
            return sorted(Path(p) for p in known if PurePosixPath(p).match(text))

        if text in known:
            return [Path(text)]

        prefix = text.rstrip("/") + "/"

        return sorted(Path(p) for p in known if p.startswith(prefix))

    if is_pattern(text):
        return sorted(p.relative_to(root) for p in root.glob(text) if p.is_file())

    target = root / text

    if target.is_file():
        return [Path(text)]

    if target.is_dir():
        return sorted(p.relative_to(root) for p in target.rglob("*") if p.is_file())

    return []


def _entries(root, raw, layout, known=None):
    """
    Read a files: list, where each item is a path, a folder, a wildcard, or a
    {from, to} pair.

    A plain entry takes its destination from the layout. A pair says exactly
    where the file goes, which is the escape hatch for a library that does not
    fit either layout, and so it can only name one file.
    """
    result = []

    for item in raw or []:
        if isinstance(item, dict):
            if "from" not in item:
                raise ManifestError(f"a files entry is missing 'from': {item!r}")

            source = Path(item["from"])
            destination = item.get("to")

            if destination and is_pattern(source):
                raise ManifestError(
                    f"'{source.as_posix()}' matches many files, so it cannot have a "
                    f"single 'to' of '{destination}'. Drop the 'to' and let the layout "
                    f"place them, or list the files one by one."
                )

            if destination:
                result.append(FileEntry(source, destination))
                continue

            raw_entry = source
        else:
            raw_entry = Path(item)

        found = expand(root, raw_entry, known)

        if not found:
            # Kept so load() can refuse it by name rather than silently
            # installing nothing, which is what a wrong pattern feels like.
            result.append(FileEntry(raw_entry, _placed(raw_entry, layout)))
            continue

        for path in found:
            result.append(FileEntry(path, _placed(path, layout, raw_entry)))

    return result


def _placed(source, layout, entry=None):
    """
    Where a file lands when the manifest does not say.

    A folder keeps its shape whatever the layout, because "copy this folder"
    only means one thing, and flattening it would collide the moment two
    subfolders held the same file name.
    """
    if entry is not None and not is_pattern(entry):
        prefix = Path(entry).as_posix().rstrip("/") + "/"
        if source.as_posix().startswith(prefix):
            return source.as_posix()

    if layout == "mirror":
        return source.as_posix()

    return source.name


class Peripheral:
    """A peripheral the user has to set up in CubeMX before the library works."""

    def __init__(self, data):
        self.type = str(data.get("type", "")).lower()
        self.count = int(data.get("count", 1))
        self.note = data.get("note", "")

    def describe(self):
        many = f" x{self.count}" if self.count > 1 else ""
        detail = f", {self.note}" if self.note else ""

        return f"{self.type.upper()}{many}{detail}"

    def __repr__(self):
        return f"Peripheral({self.type} x{self.count})"


class Requirements:
    """Everything a library needs from the project it is dropped into."""

    def __init__(self, data):
        data = data or {}
        self.libraries = [str(x) for x in (data.get("libraries") or [])]
        self.hal = bool(data.get("hal", True))
        self.cmsis = bool(data.get("cmsis", False))
        self.rtos = str(data.get("rtos", "none")).lower()
        self.hal_modules = [str(x).lower() for x in (data.get("hal_modules") or [])]
        self.peripherals = [Peripheral(entry) for entry in (data.get("peripherals") or [])]
        self.c_standard = str(data.get("c_standard", "c11")).lower()

    @property
    def needs_rtos(self):
        """True when the library will not work without an operating system."""
        return self.rtos not in ("none", "optional")

    def is_empty(self):
        """True when there is nothing worth telling the user about."""
        return not (self.libraries or self.hal_modules or self.peripherals or self.needs_rtos)


class Manifest:
    """What a library.yml says about one library."""

    def __init__(self, root, data, known=None):
        self.root = Path(root)
        self.name = data["name"]
        self.description = data.get("description", "")
        self.repository = data.get("repository", "")
        self.license = data.get("license", "")

        self.kind = str(data.get("kind", "driver")).lower()
        self.category = str(data.get("category", "")).lower()
        self.provides = [str(x).lower() for x in (data.get("provides") or [])]

        # A library that is an operating system satisfies an RTOS requirement,
        # whether or not whoever wrote the manifest remembered to say so.
        if self.kind == "rtos" and "rtos" not in self.provides:
            self.provides.append("rtos")

        self.requires = Requirements(data.get("requires"))

        install = data.get("install") or {}
        self.layout = str(install.get("layout", "flat")).lower()

        files = data["files"]
        self.headers = _entries(self.root, files.get("headers"), self.layout, known)
        self.sources = _entries(self.root, files.get("sources"), self.layout, known)

        # The version lives in the code, in the @version tag of the first
        # header's file comment, so it cannot drift from what it describes. A
        # version written in library.yml is only a fallback, for a header that
        # does not carry one.
        declared = data.get("version")
        self.version = _header_version(self.root, self.headers) or (
            str(declared) if declared is not None else ""
        )
        # "to" is optional. The file normally keeps its own name, and saying
        # it twice would only be one more thing to get out of step.
        self.once = [
            OnceFile(Path(entry["from"]), entry.get("to") or Path(entry["from"]).name)
            for entry in (data.get("once") or [])
        ]

        # Which folders go on the IDE's include path, worked out from where the
        # headers actually landed unless the manifest says otherwise.
        declared = install.get("include_dirs")
        self.include_dirs = (
            [str(d).replace("\\", "/") for d in declared]
            if declared
            else sorted({entry.folder for entry in self.headers}) or ["."]
        )
        # Copied verbatim alongside the code. The Apache licence wants both of
        # these to travel with it, and NOTICE is what carries the attribution.
        # Extras are optional by nature, so an entry that matches nothing is a
        # warning rather than a refusal. Silence was the old behaviour and it
        # made a mistyped pattern look exactly like a working one.
        self.extras = []
        self.empty_extras = []

        for item in data.get("extras") or ["LICENSE.md", "NOTICE"]:
            found = expand(self.root, item, known)

            for path in found:
                self.extras.append(FileEntry(path, _placed(path, self.layout, item)))

            if not found and item not in ("LICENSE.md", "NOTICE"):
                self.empty_extras.append(str(item))

    @property
    def code_files(self):
        """Headers and sources together. These are replaced on every install."""
        return self.headers + self.sources

    @property
    def build_sources(self):
        """
        File names the IDE has to compile, as they end up in the install folder.

        A template can be a .c file, a port layer the user fills in, and that
        file has to reach the build like any other source. Leaving it out is
        silent: the file exists, the project looks right, and the link fails
        with undefined references.

        Only files a compiler can actually take are listed, and that filter
        covers `sources` as well as `once`. Keil and IAR name every file in the
        project explicitly, so anything that gets in here shows up in the IDE's
        file tree and is handed to the compiler. A README that reached it by way
        of a mistyped manifest would be visible, confusing, and a build error.
        """
        wanted = (".c", ".cpp", ".cc", ".cxx", ".s", ".asm")

        return [
            entry.destination
            for entry in list(self.sources) + list(self.once)
            if Path(entry.destination).suffix.lower() in wanted
        ]

    @property
    def required_files(self):
        """Every repository path the manifest promises. Extras are optional."""
        return [entry.source for entry in self.code_files] + [e.source for e in self.once]

    def present_extras(self):
        """Extras to copy. Already expanded, so every one of these exists."""
        return list(self.extras)

    def clashes(self):
        """
        Files claimed as both code and once.

        Code is overwritten on every install and a once file never is, so one
        claimed as both would have the user's edits quietly replaced while the
        output still reported it as kept. A wildcard that happens to sweep up
        the config header is the usual way this happens.
        """
        code = {entry.source.as_posix() for entry in self.code_files}

        return sorted(code & {entry.source.as_posix() for entry in self.once})

    def missing_files(self):
        """Files the manifest promises but the repository does not contain."""
        return [p for p in self.required_files if not (self.root / p).is_file()]

    def summary(self):
        """A one line description of what this library is, for listings."""
        parts = [self.kind]

        if self.category and self.category != self.kind:
            parts.append(self.category)

        return " / ".join(parts)

    def __repr__(self):
        return f"Manifest({self.name} {self.version} {self.kind})"


def _warnings(manifest):
    """Things worth saying out loud that are not bad enough to refuse the install."""
    found = []

    if manifest.kind not in KINDS:
        found.append(f"kind '{manifest.kind}' is not one of: {', '.join(KINDS)}")

    if manifest.category and manifest.category not in CATEGORIES:
        found.append(f"category '{manifest.category}' is not one of: {', '.join(CATEGORIES)}")

    if manifest.requires.rtos not in RTOS_CHOICES:
        found.append(f"requires.rtos '{manifest.requires.rtos}' is not one of: {', '.join(RTOS_CHOICES)}")

    if manifest.layout not in LAYOUTS:
        found.append(f"install.layout '{manifest.layout}' is not one of: {', '.join(LAYOUTS)}")

    for entry in manifest.empty_extras:
        found.append(f"extras entry '{entry}' matched no file")

    return found


def _escapes(destination):
    """
    Whether a destination would write outside the folder it was given.

    A manifest is downloaded from the internet before any of it is trusted, so a
    "to" of "../../Core/Src/main.c" has to be caught rather than obeyed.
    """
    text = str(destination)

    # A leading slash has to count here. Windows does not call "/etc/passwd"
    # absolute, because it has no drive letter, but it still resolves to the
    # root of the current drive rather than to anywhere inside the folder.
    if text.startswith(("/", "\\")):
        return True

    return Path(text).is_absolute() or ".." in Path(text).parts


def load(library_root, strict=False, known=None):
    """
    Read the library.yml at the root of a library repository.

    Args:
        library_root: the folder holding library.yml.
        strict: treat unknown kinds and categories as errors. Useful in the
            library author's own CI, too fussy for a user installing something.
        known: every path in the repository, when the files are not on disk yet.
            Folder and wildcard entries are matched against this instead.

    Returns:
        A Manifest.

    Raises:
        ManifestError, with a message aimed at a human, whenever the manifest is
        absent, malformed, or promises files that are not there.
    """
    root = Path(library_root).resolve()
    path = root / MANIFEST_NAME

    if not path.is_file():
        raise ManifestError(f"No {MANIFEST_NAME} in {root}. Is this a NimaLTD library?")

    try:
        data = yamlreader.parse(path.read_text(encoding="utf-8"))
    except yamlreader.YamlError as error:
        raise ManifestError(f"{path} is not valid YAML: {error}") from error

    if not isinstance(data, dict):
        raise ManifestError(f"{path} should hold a mapping of settings, not a bare value.")

    # Before anything else is read, since a manifest for a newer installer may
    # not even have the fields this one expects.
    check_installer(data)

    for key in ("name", "files"):
        if key not in data:
            raise ManifestError(f"{path} is missing the required '{key}' field.")

    if not isinstance(data["files"], dict):
        raise ManifestError(f"{path}: 'files' should hold 'headers' and 'sources' lists.")

    manifest = Manifest(root, data, known)

    if not manifest.code_files:
        raise ManifestError(f"{path} lists no headers and no sources, so there is nothing to install.")

    missing = manifest.missing_files()
    if missing:
        listed = ", ".join(str(p) for p in missing)
        raise ManifestError(f"{path} lists files that do not exist in the repository: {listed}")

    # Always refused, never merely warned about. A manifest can arrive over the
    # network, and a destination like "../../Core/Src/main.c" would write into
    # the user's own code rather than the folder they agreed to.
    escaping = [
        entry.destination
        for entry in manifest.code_files + manifest.once
        if _escapes(entry.destination)
    ]

    clashing = manifest.clashes()
    if clashing:
        raise ManifestError(
            f"{path} lists these as both code and configuration, so an update would "
            f"overwrite the user's settings: " + ", ".join(clashing) + ". Narrow the "
            f"pattern, or list the files one by one."
        )

    if escaping:
        raise ManifestError(
            f"{path} sends files outside the install folder, which is never allowed: "
            + ", ".join(escaping)
        )

    problems = _warnings(manifest)
    if problems and strict:
        raise ManifestError(f"{path}: " + "; ".join(problems))

    manifest.warnings = problems

    return manifest
