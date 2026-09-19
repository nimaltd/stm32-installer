"""Tests for reading and validating library.yml."""

import pytest

from stm32_installer import manifest


def test_reads_the_basics(library):
    found = manifest.load(library())

    assert found.name == "demo"
    assert found.version == "1.0.0"
    assert [p.name for p in found.headers] == ["demo.h"]
    assert [p.name for p in found.sources] == ["demo.c"]


def test_config_template_keeps_its_destination_name(library):
    found = manifest.load(library())

    assert found.config[0].source.name == "demo_config_template.h"
    assert found.config[0].destination == "demo_config.h"


def test_c_template_counts_as_a_source_to_compile(library):
    """A port layer shipped as a template still has to reach the build."""
    root = library(
        extra_files={"src/demo_port_template.c": "/* port */\n"},
        config=[
            {"from": "inc/demo_config_template.h", "to": "demo_config.h"},
            {"from": "src/demo_port_template.c", "to": "demo_port.c"},
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
