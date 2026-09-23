"""
Tests for install.py, the bootstrap that runs the installer without pip.

It is loaded from its file rather than imported, since it is a script at the root
of the repository and not part of the package.
"""

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _bootstrap():
    """A fresh copy of install.py, loaded the way Python would run it."""
    spec = importlib.util.spec_from_file_location("bootstrap_under_test", REPO / "install.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module


def test_it_uses_the_installer_beside_it_without_going_online(monkeypatch, tmp_path):
    """Kept in a download of this repository, it must work with no network at all."""
    boot = _bootstrap()

    def offline(*args, **kwargs):
        raise AssertionError("went online with the installer right beside it")

    monkeypatch.setattr(boot.urllib.request, "urlopen", offline)

    installer = boot.get_installer(tmp_path)

    assert installer is not None
    assert callable(installer.main)


def test_piped_into_python_it_has_no_folder(monkeypatch):
    """__file__ reads "<stdin>" then, which is not a place to look for anything."""
    boot = _bootstrap()
    monkeypatch.setattr(boot, "__file__", "<stdin>")

    assert boot.here() is None


def test_every_argument_reaches_the_installer_untouched(monkeypatch):
    """
    Nothing is added or taken away on the way through.

    An earlier version slipped a library name and a --ref in front, and had to
    guess which arguments were option values to avoid reading "v2.0.0" as a
    library. There is nothing left to guess now, so nothing may be changed.
    """
    boot = _bootstrap()
    seen = []

    class Installer:
        @staticmethod
        def main(argv=None):
            seen.append(argv)
            return 0

    monkeypatch.setattr(boot, "get_installer", lambda staging: Installer)

    argv = ["nimaltd/demo", "--ref", "2.0.0", "--dir", "Libs/demo"]

    assert boot.main(list(argv)) == 0
    assert seen == [argv]


def test_without_arguments_it_explains_itself(capsys):
    boot = _bootstrap()

    assert boot.main([]) == 2
    assert "Say what to install" in capsys.readouterr().err
