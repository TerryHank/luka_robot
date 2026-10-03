from pathlib import Path
import xml.etree.ElementTree as ET


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def test_package_uses_rosdep_pytest_dependency():
    package = ET.parse(PACKAGE_ROOT / "package.xml").getroot()
    test_dependencies = [dependency.text for dependency in package.findall("test_depend")]

    assert test_dependencies == ["python3-pytest"]
    assert "pytest" not in test_dependencies


def test_setup_omits_deprecated_tests_require():
    setup_source = (PACKAGE_ROOT / "setup.py").read_text(encoding="utf-8")

    assert "tests_require" not in setup_source
