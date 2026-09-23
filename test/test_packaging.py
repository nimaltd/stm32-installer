"""
The package metadata, which pip reads before any of the code runs.

Read as text rather than with tomllib, which only arrived in Python 3.11, and the
tests still run on 3.8.
"""

import re
from pathlib import Path

PYPROJECT = (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text(encoding="utf-8")


def test_the_command_is_called_stm32_installer():
    assert re.search(r'^stm32-installer = "stm32_installer\.cli:main"$', PYPROJECT, re.M)


def test_nothing_has_to_be_downloaded_to_install_it():
    """
    PyYAML is optional in the code. Listing it here would send pip online to get
    it, and break the one kind of install that has to work without a network.
    """
    found = re.search(r"^dependencies = \[(.*?)\]", PYPROJECT, re.M | re.S)

    assert found is not None
    assert found.group(1).strip() == ""
