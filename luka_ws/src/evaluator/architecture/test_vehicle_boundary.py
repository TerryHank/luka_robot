import ast

from .source_checks import ROOT, imported_modules, sources


# Commissioning implementations now live in the Base boundary. Console
# compatibility commands import only their canonical wrappers.
LEGACY_IMPORTS = {}


def test_no_new_driver_imports_outside_vehicle_implementation():
    found = {}
    for path in sources(ROOT):
        relative = path.relative_to(ROOT).as_posix()
        if relative.startswith(("control/ddsm_car_control/", "control/luka_base_gate/", "vehicle/", "evaluator/")):
            continue
        source = path.read_text(encoding="utf-8")
        if "ddsm_car_control" not in source:
            continue
        imports = {name for name in imported_modules(ast.parse(source, filename=relative))
                   if name == "ddsm_car_control" or name.startswith("ddsm_car_control.")}
        if imports:
            found[relative] = imports
    assert found == LEGACY_IMPORTS, f"Driver boundary changed: {found}"


def test_driver_import_aliases_are_detected():
    assert imported_modules(ast.parse("import ddsm_car_control as driver")) == {"ddsm_car_control"}
    assert imported_modules(ast.parse("from ddsm_car_control.zdt_y42_protocol import ZDTY42SerialBus as Bus")) == {
        "ddsm_car_control.zdt_y42_protocol"}
