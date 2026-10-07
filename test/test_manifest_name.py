"""
Tests for the manifest's name: installer.yml, and library.yml before 1.9.0.

The file was renamed in 1.9.0. A release tagged before that has only
library.yml, and --ref can still ask for one, so the old name is read when the
new one is not there, on disk and on GitHub alike. When both are there, the new
one is the manifest.
"""

import pytest

from stm32_installer import download, installer, manifest

from test_download import _ref_of, github  # noqa: F401  the fake GitHub fixture

OLD = b"name: old\nfiles:\n  headers:\n    - demo.h\n  sources:\n    - demo.c\n"
NEW = b"name: new\nfiles:\n  headers:\n    - demo.h\n  sources:\n    - demo.c\n"


def _repo(tmp_path, names):
    """A library folder holding the manifest under these names."""
    root = tmp_path / "demo"
    root.mkdir()
    (root / "demo.h").write_text("/* h */\n", encoding="utf-8")
    (root / "demo.c").write_text("/* c */\n", encoding="utf-8")

    for name in names:
        (root / name).write_bytes(OLD if name == "library.yml" else NEW)

    return root


def test_the_manifest_is_called_installer_yml():
    assert manifest.MANIFEST_NAME == "installer.yml"


def test_a_folder_with_only_the_old_name_still_loads(tmp_path):
    assert manifest.load(_repo(tmp_path, ["library.yml"])).name == "old"


def test_the_new_name_wins_when_both_are_there(tmp_path):
    assert manifest.load(_repo(tmp_path, ["installer.yml", "library.yml"])).name == "new"


def test_a_folder_with_neither_names_the_new_one(tmp_path):
    with pytest.raises(manifest.ManifestError, match="No installer.yml"):
        manifest.load(_repo(tmp_path, []))


def test_a_zip_with_the_old_name_is_found(tmp_path):
    root = _repo(tmp_path, ["library.yml"])

    assert download.find_root(root) == root
    assert download.find_root(tmp_path) == root


def test_installing_in_place_removes_either_name(tmp_path):
    root = _repo(tmp_path, ["installer.yml", "library.yml"])

    installer.install_in_place(manifest.load(root), project_root=tmp_path)

    assert not (root / "installer.yml").exists()
    assert not (root / "library.yml").exists()


def test_github_is_asked_for_the_new_name_first(github, tmp_path):
    github.files["library.yml"] = OLD

    download.fetch("someone/demo", destination=tmp_path / "lib")

    asked = [url.split("?")[0].rsplit("/", 1)[1] for url, _ in github.seen]

    assert asked[0] == "installer.yml"
    assert "library.yml" not in asked
    assert manifest.load(tmp_path / "lib").name == "demo"


def test_a_release_from_before_the_rename_installs(github, tmp_path):
    """--ref v2.0.0 asks for a tag that has only library.yml."""
    del github.files["installer.yml"]
    github.files["library.yml"] = OLD

    download.fetch("someone/demo", ref="v2.0.0", destination=tmp_path / "lib")

    assert (tmp_path / "lib" / "library.yml").read_bytes() == OLD
    assert manifest.load(tmp_path / "lib").name == "old"
    assert {_ref_of(url) for url, _ in github.seen} == {"v2.0.0"}


def test_neither_name_on_github_says_the_new_one(github, tmp_path):
    del github.files["installer.yml"]

    with pytest.raises(download.DownloadError) as raised:
        download.fetch("someone/demo", ref="v9", destination=tmp_path / "lib")

    assert "installer.yml does not exist in someone/demo at v9" in str(raised.value)
    assert "GITHUB_TOKEN" in str(raised.value)
