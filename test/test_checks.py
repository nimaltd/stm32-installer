"""Tests for checking a project against what a library needs."""

from stm32_installer import checks, manifest

HAL_CONF = (
    "#define HAL_MODULE_ENABLED\n"
    "#define HAL_GPIO_MODULE_ENABLED\n"
    "/*#define HAL_SPI_MODULE_ENABLED   */\n"
)

IOC = "Mcu.IP0=NVIC\nMcu.IP1=RCC\nMcu.IP2=GPIO\nMcu.IP3=USART2\n"
IOC_WITH_RTOS = IOC + "Mcu.IP4=FREERTOS\n"


def _levels(findings):
    return [(f.level, f.message) for f in findings]


def test_a_library_that_needs_nothing_reports_nothing(library, project):
    lib = manifest.load(library())
    root = project(hal_conf=HAL_CONF, ioc=IOC)

    assert checks.check(lib, root) == []


def test_a_commented_out_hal_module_counts_as_disabled(project):
    """CubeMX leaves the define in place, commented, which is easy to misread."""
    root = project(hal_conf=HAL_CONF)
    enabled = checks.enabled_hal_modules(checks.find_hal_conf(root))

    assert "gpio" in enabled
    assert "spi" not in enabled


def test_a_disabled_hal_module_is_flagged(library, project):
    lib = manifest.load(library(requires={"hal_modules": ["spi"]}))
    root = project(hal_conf=HAL_CONF, ioc=IOC)

    findings = checks.check(lib, root)

    assert any(level == checks.WARN and "SPI" in message for level, message in _levels(findings))


def test_an_enabled_hal_module_passes(library, project):
    lib = manifest.load(library(requires={"hal_modules": ["gpio"]}))
    root = project(hal_conf=HAL_CONF, ioc=IOC)

    findings = checks.check(lib, root)

    assert any(level == checks.OK for level, _ in _levels(findings))


def test_a_peripheral_matches_any_numbered_instance(library, project):
    """A library asking for uart is satisfied by USART2."""
    lib = manifest.load(library(requires={"peripherals": [{"type": "usart"}]}))
    root = project(hal_conf=HAL_CONF, ioc=IOC)

    findings = checks.check(lib, root)

    assert all(f.level != checks.WARN for f in findings)


def test_a_missing_peripheral_is_flagged_with_what_is_needed(library, project):
    lib = manifest.load(
        library(requires={"peripherals": [{"type": "spi", "note": "Master mode"}]})
    )
    root = project(hal_conf=HAL_CONF, ioc=IOC)

    findings = checks.check(lib, root)
    warnings = [f for f in findings if f.level == checks.WARN]

    assert warnings
    assert "Master mode" in warnings[0].hint


def test_a_missing_rtos_is_flagged(library, project):
    lib = manifest.load(library(requires={"rtos": "freertos"}))
    root = project(hal_conf=HAL_CONF, ioc=IOC)

    findings = checks.check(lib, root)

    assert any("RTOS" in f.message for f in findings if f.level == checks.WARN)


def test_freertos_in_the_ioc_satisfies_the_requirement(library, project):
    lib = manifest.load(library(requires={"rtos": "freertos"}))
    root = project(hal_conf=HAL_CONF, ioc=IOC_WITH_RTOS)

    findings = checks.check(lib, root)

    assert any(f.level == checks.OK and "freertos" in f.message for f in findings)


def test_a_different_rtos_is_a_warning_not_a_refusal(library, project):
    lib = manifest.load(library(requires={"rtos": "threadx"}))
    root = project(hal_conf=HAL_CONF, ioc=IOC_WITH_RTOS)

    findings = checks.check(lib, root)

    assert any(f.level == checks.WARN and "threadx" in f.message for f in findings)


def test_any_rtos_is_satisfied_by_whatever_is_there(library, project):
    lib = manifest.load(library(requires={"rtos": "any"}))
    root = project(hal_conf=HAL_CONF, ioc=IOC_WITH_RTOS)

    findings = checks.check(lib, root)

    assert all(f.level != checks.WARN for f in findings)


def test_a_project_with_no_cubemx_files_is_reported_as_unverified(library, tmp_path):
    """Being unable to check must never read as everything being fine."""
    lib = manifest.load(library(requires={"hal_modules": ["spi"]}))

    findings = checks.check(lib, tmp_path)

    assert len(findings) == 1
    assert findings[0].level == checks.INFO
