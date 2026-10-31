"""Frappe v16 apps-screen visibility for the ZATCA tile."""
import frappe


def can_see():
    roles = set(frappe.get_roles())
    return bool(roles & {"System Manager", "Accounts User", "Accounts Manager"})
