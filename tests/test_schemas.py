"""Every example validates against its schema, and extensions are never rejected."""
import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = {p.name: json.loads(p.read_text()) for p in (ROOT / "schemas/v1").glob("*.json")}
REGISTRY = Registry().with_resources(
    (name, Resource.from_contents(s)) for name, s in SCHEMAS.items()
).with_resources((s["$id"], Resource.from_contents(s)) for s in SCHEMAS.values())
BY_TYPE = {"outus/" + n.removesuffix(".schema.json"): s for n, s in SCHEMAS.items() if n != "common.schema.json"}
EXAMPLES = sorted((ROOT / "examples").rglob("*.json"))


def validate(doc):
    v = Draft202012Validator(BY_TYPE[doc["type"]], registry=REGISTRY, format_checker=FormatChecker())
    return sorted(e.message for e in v.iter_errors(doc))


def test_schemas_are_valid():
    for s in SCHEMAS.values():
        Draft202012Validator.check_schema(s)


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_example_validates(path):
    assert validate(json.loads(path.read_text())) == []


def test_every_document_type_has_an_example():
    types = {json.loads(p.read_text())["type"] for p in EXAMPLES}
    assert types == set(BY_TYPE)


def test_extensions_are_accepted():
    """Unknown fields and other commodities are extensions: valid, preserved, never dropped."""
    doc = json.loads((ROOT / "examples/electricity/au-tou-plan.json").read_text())
    ext = copy.deepcopy(doc)
    ext["x-example"] = {"anything": 1}
    ext["meter"]["commodity"] = "gas"
    ext["meter"]["unit"] = "MJ"
    ext["tariffs"][0]["charges"][0]["x-note"] = "kept"
    assert validate(ext) == []


def test_a_charge_needs_its_class():
    doc = json.loads((ROOT / "examples/electricity/au-tou-plan.json").read_text())
    del doc["tariffs"][0]["charges"][0]["class"]
    assert any("'class' is a required property" in m for m in validate(doc))


def test_a_plan_needs_a_tariff():
    doc = json.loads((ROOT / "examples/electricity/au-tou-plan.json").read_text())
    doc["tariffs"] = []
    assert validate(doc)
