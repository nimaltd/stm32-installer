"""Tests for reading and validating library.yml."""

from pathlib import Path

import pytest

from stm32_installer import manifest


def test_reads_the_basics(library):
    found = manifest.load(library())

    assert found.name == "demo"
    assert found.version == "1.0.0"
    assert [e.destination for e in found.headers] == ["demo.h"]
    assert [e.destination for e in found.sources] == ["demo.c"]


def test_a_template_keeps_its_own_name_when_no_destination_is_given(library):
    """Templates sit in template/ under their final name, so "to" is redundant."""
    found = manifest.load(library())

    assert found.config[0].source == Path("template/demo_config.h")
    assert found.config[0].destination == "demo_config.h"


def test_an_explicit_destination_still_wins(library):
    root = library(config=[{"from": "template/demo_config.h", "to": "renamed.h"}])

    found = manifest.load(root)

    assert found.config[0].destination == "renamed.h"


def test_c_template_counts_as_a_source_to_compile(library):
    """A port layer shipped as a template still has to reach the build."""
    root = library(
        extra_files={"template/demo_port.c": "/* port */\n"},
        config=[
            {"from": "template/demo_config.h"},
            {"from": "template/demo_port.c"},
        ],
    )

    found = manifest.load(root)

    assert found.build_sources == ["demo.c", "demo_port.c"]


def test_header_template_is_not_a_source(library):
    found = manifest.load(library())

    assert found.build_sources == ["demo.c"]


def test_an_rtos_library_provides_rtos_without_saying_so(library):
    found = manifest.load(library(kind="rtos"))

    assert "rtos" in found.provides


def test_missing_manifest_is_reported_clearly(tmp_path):
    with pytest.raises(manifest.ManifestError, match="No library.yml"):
        manifest.load(tmp_path)


def test_a_manifest_promising_absent_files_is_refused(library):
    root = library()
    (root / "src" / "demo.c").unlink()

    with pytest.raises(manifest.ManifestError, match="do not exist"):
        manifest.load(root)


def test_a_manifest_with_no_code_is_refused(library):
    root = library(headers=[], sources=[])

    with pytest.raises(manifest.ManifestError, match="nothing to install"):
        manifest.load(root)


def test_broken_yaml_is_reported_as_yaml(library):
    root = library()
    (root / "library.yml").write_text("name: demo\n  bad indent: [", encoding="utf-8")

    with pytest.raises(manifest.ManifestError, match="not valid YAML"):
        manifest.load(root)


def test_unknown_kind_warns_but_still_loads(library):
    found = manifest.load(library(kind="nonsense"))

    assert found.warnings
    assert "nonsense" in found.warnings[0]


def test_unknown_kind_is_an_error_in_strict_mode(library):
    with pytest.raises(manifest.ManifestError):
        manifest.load(library(kind="nonsense"), strict=True)


def test_requirements_default_to_nothing_interesting(library):
    found = manifest.load(library())

    assert found.requires.is_empty()
    assert not found.requires.needs_rtos


def test_optional_rtos_does_not_count_as_needing_one(library):
    found = manifest.load(library(requires={"rtos": "optional"}))

    assert not found.requires.needs_rtos


def test_named_rtos_counts_as_needing_one(library):
    found = manifest.load(library(requires={"rtos": "freertos"}))

    assert found.requires.needs_rtos


def test_flat_layout_puts_everything_at_the_top(library):
    found = manifest.load(library())

    assert found.layout == "flat"
    assert [e.destination for e in found.headers] == ["demo.h"]
    assert found.include_dirs == ["."]


def test_mirror_layout_keeps_the_repository_folders(library):
    root = library(install={"layout": "mirror"})

    found = manifest.load(root)

    assert [e.destination for e in found.headers] == ["inc/demo.h"]
    assert [e.destination for e in found.sources] == ["src/demo.c"]
    assert found.include_dirs == ["inc"]


def test_a_file_can_name_its_own_destination(library):
    root = library(
        headers=[{"from": "inc/demo.h", "to": "api/demo.h"}],
        extra_files={"inc/demo.h": "/* h */\n"},
    )

    found = manifest.load(root)

    assert [e.destination for e in found.headers] == ["api/demo.h"]
    assert found.include_dirs == ["api"]


def test_include_dirs_can_be_stated_outright(library):
    root = library(install={"layout": "mirror", "include_dirs": ["inc", "inc/port"]})

    found = manifest.load(root)

    assert found.include_dirs == ["inc", "inc/port"]


def test_a_destination_escaping_the_folder_is_refused(library):
    """A manifest arrives over the network, so this can never be a warning."""
    root = library(headers=[{"from": "inc/demo.h", "to": "../../Core/Src/main.c"}])

    with pytest.raises(manifest.ManifestError, match="outside the install folder"):
        manifest.load(root)


def test_an_absolute_destination_is_refused(library):
    root = library(headers=[{"from": "inc/demo.h", "to": "/etc/passwd"}])

    with pytest.raises(manifest.ManifestError, match="outside the install folder"):
        manifest.load(root)
