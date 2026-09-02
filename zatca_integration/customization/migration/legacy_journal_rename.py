"""One-time, manifest-scoped restoration of January-2024 Journal Entry names.

This intentionally uses Frappe's ``rename_doc`` API rather than SQL.  It is
limited to the already-posted January-2024 migration population and refuses to
run if the live state differs from the approved preflight.
"""

from __future__ import annotations

from collections import Counter

import frappe
from frappe import _


PILOT_REMARK = "January 2024 pilot"
OPENING_CURRENT = "ACC-JV-2026-00045"
OPENING_LEGACY = "ACC-JV-2024-02189-2"
EXPECTED_PILOT_COUNT = 266
CONFIRMATION = "RENAME_JAN_2024_LEGACY_IDS"
ONE_CONFIRMATION = "RENAME_ONE_JAN_2024_LEGACY_ID"


def _only_migration_admins():
    frappe.only_for(("System Manager", "Accounts Manager"))


def _legacy_id(row):
    value = (row.get("custom_legacy_id") or "").strip()
    return value if value.startswith("ACC-JV-") else ""


def _pilot_rows():
    rows = frappe.get_all(
        "Journal Entry",
        filters={"docstatus": 1, "user_remark": ("like", f"%{PILOT_REMARK}%")},
        fields=["name", "posting_date", "docstatus", "custom_legacy_id", "user_remark"],
        order_by="posting_date asc, name asc",
        limit_page_length=0,
    )
    rows = [row for row in rows if _legacy_id(row)]
    if len(rows) != EXPECTED_PILOT_COUNT:
        frappe.throw(
            _("Expected {0} submitted January pilot Journal Entries; found {1}.").format(
                EXPECTED_PILOT_COUNT, len(rows)
            )
        )
    return rows


def _plan():
    rows = _pilot_rows()
    opening_name = OPENING_CURRENT if frappe.db.exists("Journal Entry", OPENING_CURRENT) else OPENING_LEGACY
    opening = frappe.db.get_value(
        "Journal Entry", opening_name, ["name", "posting_date", "docstatus"], as_dict=True
    )
    if not opening or opening.docstatus != 1 or str(opening.posting_date) != "2024-01-01":
        frappe.throw(_("Opening Journal Entry precondition failed."))

    expected = {row.name: _legacy_id(row) for row in rows}
    expected[opening_name] = OPENING_LEGACY
    desired = list(expected.values())
    if len(set(desired)) != len(desired):
        duplicates = [name for name, count in Counter(desired).items() if count > 1]
        frappe.throw(_("Duplicate desired legacy names: {0}").format(", ".join(duplicates)))

    # A verified pilot rename may already have put one or more documents at the
    # exact legacy name.  Keep them in the identity audit, but omit them from
    # the remaining mutation plan so re-running is safe.
    mappings = {old: new for old, new in expected.items() if old != new}
    approved_current = set(expected)
    all_names = set(frappe.get_all("Journal Entry", pluck="name", limit_page_length=0))
    occupied_outside_scope = sorted(name for name in desired if name in all_names and name not in approved_current)
    if occupied_outside_scope:
        frappe.throw(_("Legacy names already occupied outside the approved scope: {0}").format(", ".join(occupied_outside_scope)))

    # Topological rename order: first move a document whose desired name is not
    # still occupied by another source document.  A temporary name is needed only
    # for a true cycle, never for an ordinary chain.
    pending = dict(mappings)
    steps = []
    temporary = []
    sequence = 0
    while pending:
        remaining_current = set(pending)
        ready = sorted(old for old, new in pending.items() if new not in remaining_current)
        if ready:
            old = ready[0]
            steps.append({"from": old, "to": pending.pop(old), "temporary": False})
            continue
        old = sorted(pending)[0]
        temp = f"__SIG_LEGACY_RENAME_TMP_{sequence:03d}__"
        sequence += 1
        if temp in all_names:
            frappe.throw(_("Temporary rename collision: {0}").format(temp))
        desired_name = pending.pop(old)
        steps.append({"from": old, "to": temp, "temporary": True})
        pending[temp] = desired_name
        all_names.add(temp)
        temporary.append(temp)

    return {
        "count": len(mappings),
        "approved_count": len(expected),
        "already_correct": len(expected) - len(mappings),
        "mappings": mappings,
        "steps": steps,
        "temporary_names": temporary,
        "opening": {"current": opening_name, "legacy": OPENING_LEGACY},
    }


def _enable_rename():
    """Enable the framework-supported rename flag through a Property Setter."""
    setter = frappe.db.exists(
        "Property Setter",
        {"doc_type": "Journal Entry", "doctype_or_field": "DocType", "property": "allow_rename"},
    )
    if setter:
        doc = frappe.get_doc("Property Setter", setter)
        if doc.value != "1":
            doc.value = "1"
            doc.save(ignore_permissions=True)
    else:
        frappe.get_doc(
            {
                "doctype": "Property Setter",
                "doc_type": "Journal Entry",
                "doctype_or_field": "DocType",
                "property": "allow_rename",
                "property_type": "Check",
                "value": "1",
            }
        ).insert(ignore_permissions=True)
    frappe.clear_cache(doctype="Journal Entry")
    if not frappe.get_meta("Journal Entry").allow_rename:
        frappe.throw(_("Could not enable the Journal Entry Allow Rename property."))


def _gl_control(names):
    rows = frappe.get_all(
        "GL Entry",
        filters={"voucher_type": "Journal Entry", "voucher_no": ("in", names), "is_cancelled": 0},
        fields=["voucher_no", "debit", "credit"],
        limit_page_length=0,
    )
    return {
        "rows": len(rows),
        "debit": round(sum(row.debit or 0 for row in rows), 2),
        "credit": round(sum(row.credit or 0 for row in rows), 2),
    }


@frappe.whitelist()
def preflight_january_2024_legacy_rename():
    """Return the exact read-only rename plan. No document is modified."""
    _only_migration_admins()
    plan = _plan()
    plan["gl_before"] = _gl_control(list(plan["mappings"]))
    return plan


@frappe.whitelist()
def apply_one_january_2024_legacy_rename(current_name, confirmation):
    """Prove the framework rename path on one approved submitted pilot JE."""
    _only_migration_admins()
    if confirmation != ONE_CONFIRMATION:
        frappe.throw(_("Exact one-document confirmation is required; no Journal Entry was renamed."))

    plan = _plan()
    desired_name = plan["mappings"].get(current_name)
    if not desired_name:
        frappe.throw(_("The requested Journal Entry is not an unrenamed approved pilot document."))
    gl_before = _gl_control([current_name])
    if not gl_before["rows"] or gl_before["debit"] != gl_before["credit"]:
        frappe.throw(_("Pre-rename GL control is not balanced."))

    _enable_rename()
    frappe.rename_doc("Journal Entry", current_name, desired_name, merge=False, force=False)
    if not frappe.db.exists("Journal Entry", desired_name):
        frappe.throw(_("Post-rename document existence check failed."))
    gl_after = _gl_control([desired_name])
    if gl_after != gl_before:
        frappe.throw(_("Post-rename GL control changed; stop and restore the backup."))
    frappe.get_doc("Journal Entry", desired_name).add_comment(
        "Info", "Legacy Journal Entry name restored by approved January-2024 migration pilot."
    )
    return {"renamed": {"from": current_name, "to": desired_name}, "gl_before": gl_before, "gl_after": gl_after}


@frappe.whitelist()
def apply_january_2024_legacy_rename(confirmation):
    """Rename only the approved 266 January JEs and opening JE after preflight."""
    _only_migration_admins()
    if confirmation != CONFIRMATION:
        frappe.throw(_("Exact confirmation is required; no Journal Entry was renamed."))

    plan = _plan()
    old_names = list(plan["mappings"])
    gl_before = _gl_control(old_names)
    if not gl_before["rows"] or gl_before["debit"] != gl_before["credit"]:
        frappe.throw(_("Pre-rename GL control is not balanced."))

    _enable_rename()
    for step in plan["steps"]:
        frappe.rename_doc("Journal Entry", step["from"], step["to"], merge=False, force=False)

    new_names = list(plan["mappings"].values())
    if any(not frappe.db.exists("Journal Entry", name) for name in new_names):
        frappe.throw(_("Post-rename document existence check failed."))
    gl_after = _gl_control(new_names)
    if gl_after != gl_before:
        frappe.throw(_("Post-rename GL control changed; stop and restore the backup."))

    for name in new_names:
        frappe.get_doc("Journal Entry", name).add_comment("Info", "Legacy Journal Entry name restored by approved January-2024 migration.")
    return {"renamed": len(new_names), "gl_before": gl_before, "gl_after": gl_after, "temporary_names": plan["temporary_names"]}
