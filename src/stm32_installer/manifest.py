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

from pathlib import Path

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


# How files are laid out inside the folder they are installed into.
LAYOUTS = (
    "flat",    # every file at the top, so one include path covers the library
    "mirror",  # keep the repository's own folders, for a library too big to flatten
)


class ConfigFile:
    """A template copied once, which then belongs to the user."""

    def __init__(self, source, destination):
        self.source = source
        self.destination = destination

    def __repr__(self):
        return f"ConfigFile({self.source!r} -> {self.destination!r})"


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


def _entries(raw, layout):
    """
    Read a files: list, where each item is a path or a {from, to} pair.

    A plain path takes its destination from the layout. A pair says exactly
    where the file goes, which is the escape hatch for a library that does not
    fit either layout.
    """
    result = []

    for item in raw or []:
        if isinstance(item, dict):
            if "from" not in item:
                raise ManifestError(f"a files entry is missing 'from': {item!r}")
            source = Path(item["from"])
            destination = item.get("to") or _placed(source, layout)
        else:
            source = Path(item)
            destination = _placed(source, layout)

        result.append(FileEntry(source, destination))

    return result


def _placed(source, layout):
    """Where a file lands when the manifest does not say."""
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

    def __init__(self, root, data):
        self.root = Path(root)
        self.name = data["name"]
        self.version = str(data.get("version", "0.0.0"))
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
        self.headers = _entries(files.get("headers"), self.layout)
        self.sources = _entries(files.get("sources"), self.layout)
        # "to" is optional. Templates live in template/ under their final name,
        # so the destination is normally just the file name, and saying it twice
        # would only be one more thing to get out of step.
        self.config = [
            ConfigFile(Path(entry["from"]), entry.get("to") or Path(entry["from"]).name)
            for entry in (data.get("config") or [])
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
        self.extras = [Path(p) for p in (data.get("extras") or ["LICENSE.md", "NOTICE"])]

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
        """
        names = [entry.destination for entry in self.sources]
        names += [
            entry.destination
            for entry in self.config
            if Path(entry.destination).suffix.lower() in (".c", ".cpp", ".cc", ".s")
        ]

        return names

    @property
    def required_files(self):
        """Every repository path the manifest promises. Extras are optional."""
        return [entry.source for entry in self.code_files] + [e.source for e in self.config]

    def present_extras(self):
        """Extras that actually exist. A repository without a NOTICE is still valid."""
        return [p for p in self.extras if (self.root / p).is_file()]

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


def load(library_root, strict=False):
    """
    Read the library.yml at the root of a library repository.

    Args:
        library_root: the folder holding library.yml.
        strict: treat unknown kinds and categories as errors. Useful in the
            library author's own CI, too fussy for a user installing something.

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

    for key in ("name", "files"):
        if key not in data:
            raise ManifestError(f"{path} is missing the required '{key}' field.")

    if not isinstance(data["files"], dict):
        raise ManifestError(f"{path}: 'files' should hold 'headers' and 'sources' lists.")

    manifest = Manifest(root, data)

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
        for entry in manifest.code_files + manifest.config
        if _escapes(entry.destination)
    ]

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
