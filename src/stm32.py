"""
What stm32-installer adds to the shared core: what an STM32 project is.

The core does everything a library needs whatever it is installed into. This
says the rest for STM32: the requirements an installer.yml can state, checked
against the CubeMX project by checks.py, and the IDE project files that ide/
registers the library with.
"""

from . import checks, ide
from .core.target import Target

# How a library relates to an operating system.
RTOS_CHOICES = (
    "none",        # bare metal, does not care
    "optional",    # works either way
    "any",         # needs some RTOS, does not mind which
    "freertos",
    "cmsis-os2",
    "threadx",
)


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


class Stm32(Target):
    """An STM32 project, made by CubeMX and built with any IDE it supports."""

    name = "stm32-installer"
    record_name = ".stm32-installer.json"
    project = "STM32 project"
    integrations = ("cmake", "cubeide", "keil", "iar", "makefile")
    no_project = "No IDE project was recognised here, so nothing was registered."
    no_project_hint = "Add the folder to your include paths and the .c files to your build."

    def __init__(self, version):
        self.version = version

    def read_requirements(self, requirements, data):
        """The STM32 part of requires: the HAL, the RTOS, and what CubeMX sets up."""
        requirements.hal = bool(data.get("hal", True))
        requirements.cmsis = bool(data.get("cmsis", False))
        requirements.rtos = str(data.get("rtos", "none")).lower()
        requirements.hal_modules = [str(x).lower() for x in (data.get("hal_modules") or [])]
        requirements.peripherals = [Peripheral(entry) for entry in (data.get("peripherals") or [])]
        requirements.c_standard = str(data.get("c_standard", "c11")).lower()

        # True when the library will not work without an operating system.
        requirements.needs_rtos = requirements.rtos not in ("none", "optional")

    def requirements_empty(self, requirements):
        return not (requirements.hal_modules or requirements.peripherals or requirements.needs_rtos)

    def warnings(self, manifest):
        rtos = manifest.requires.rtos

        if rtos in RTOS_CHOICES:
            return []

        return [f"requires.rtos '{rtos}' is not one of: {', '.join(RTOS_CHOICES)}"]

    def check(self, library, project_root):
        return checks.check(library, project_root)

    def integrate(self, project_root, library, destination, only=None, dropped=(),
                  dropped_defines=()):
        return ide.integrate(project_root, library, destination, only=only, dropped=dropped,
                             dropped_defines=dropped_defines)

    def uninstall(self, project_root, library):
        return ide.uninstall(project_root, library)
