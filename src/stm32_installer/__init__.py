"""
Install NimaLTD embedded C libraries into an STM32 project.

Two ways in. A user who downloaded a library repository into their project runs
its install.py, which flattens the repository into a usable library folder. A
user running the one line command from a README downloads the library first and
is asked where to put it.

See https://github.com/nimaltd/stm32-installer
"""

from .installer import InstallError, Result, install_in_place, install_to
from .manifest import Manifest, ManifestError, load

__version__ = "1.0.0"

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
