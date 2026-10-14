"""
Install embedded C libraries into an STM32 project.

Installed with pip, it is the stm32-installer command. It takes a library from
GitHub, from a downloaded zip, or from a folder.

The work that is the same for any project is the shared core, in core/, from
github.com/nimaltd/core-installer. What an STM32 project is, is in stm32.py.

See https://github.com/nimaltd/stm32-installer
"""

__version__ = "1.11.1"

# Before anything of the core is used: it asks the platform for every answer
# that depends on the kind of project.
from .core import target as _target  # noqa: E402
from .stm32 import Stm32  # noqa: E402

_target.use(Stm32(__version__))

from .core.installer import InstallError, Result, install_in_place, install_to  # noqa: E402
from .core.manifest import Manifest, ManifestError, load  # noqa: E402

__all__ = [
    "InstallError",
    "Manifest",
    "ManifestError",
    "Result",
    "install_in_place",
    "install_to",
    "load",
    "main",
]


def main(argv=None, library_root=None):
    """Run the command line interface. Imported lazily to keep start-up cheap."""
    from .cli import main as _main

    return _main(argv=argv, library_root=library_root)
