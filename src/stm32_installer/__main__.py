"""Lets the package be run directly: python -m stm32_installer nimaltd/example"""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
