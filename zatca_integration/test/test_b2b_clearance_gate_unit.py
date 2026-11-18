"""Exercise the clearance gate without a live ZATCA request."""
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest


def gate(enabled=True, auto=False, customer_type="Company"):
    source = (Path(__file__).parents[1] / "clearence_util.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "enforce_b2b_clearance_on_submit")
    def get_value(doctype, name, field):
        return enabled if doctype == "Company" else customer_type
    def reject(message):
        raise ValueError(message)
    namespace = {"frappe": SimpleNamespace(db=SimpleNamespace(get_value=get_value), throw=reject),
                 "get_auto_sales_submission": lambda company: auto,
                 "is_legacy_import": lambda doc: doc.get("custom_is_legacy_import") in (1, "1", True)}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "clearence_util.py", "exec"), namespace)
    return namespace[fn.name]


class Invoice(dict):
    company = "Company"
    customer = "Customer"


def test_synchronous_company_requires_clearance():
    check = gate()
    with pytest.raises(ValueError, match="clearance"):
        check(Invoice(custom_zatca_submit_status="NOT_CLEARED"))
    check(Invoice(custom_zatca_submit_status="CLEARED"))


def test_legacy_generation_returns_before_company_or_network_access():
    source = (Path(__file__).parents[1] / "clearence_util.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "generate_einvoice"]
    namespace = {"is_legacy_import": lambda doc: doc.get("custom_is_legacy_import") in (1, "1", True)}
    exec(compile(ast.Module(body=functions, type_ignores=[]), "clearence_util.py", "exec"), namespace)
    assert namespace["generate_einvoice"](Invoice(custom_is_legacy_import=1)) is None


def test_nonlegacy_string_zero_does_not_bypass_clearance():
    with pytest.raises(ValueError, match="clearance"):
        gate()(Invoice(custom_is_legacy_import="0", custom_zatca_submit_status="DRAFT"))


@pytest.mark.parametrize("kwargs,doc", [
    ({"auto": True}, {}),
    ({"customer_type": "Individual"}, {}),
    ({"enabled": False}, {}),
    ({}, {"custom_is_zatca_test": 1}),
    ({}, {"custom_is_legacy_import": 1}),
    ({}, {"custom_is_legacy_import": "1"}),
])
def test_non_synchronous_or_exempt_paths_are_unchanged(kwargs, doc):
    gate(**kwargs)(Invoice(doc))

