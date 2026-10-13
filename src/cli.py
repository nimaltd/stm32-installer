"""
The stm32-installer command: the core's command line, with the STM32 platform.

The platform is chosen when the package is imported, before this runs. Kept as
stm32_installer.cli because an install.py from an older library release imports
main from here and passes library_root.
"""

import sys

from .core.cli import main

__all__ = ["main"]

if __name__ == "__main__":
    sys.exit(main())
