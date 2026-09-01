from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from zatca_integration.clearence_util import (
    bg_generate_einvoice,
    bulk_resend_einvoices,
    enforce_b2b_clearance_on_submit,
    generate_einvoice,
    generate_einvoice_on_submit,
    resend_einvoice,
)
from zatca_integration.common_util import validate_sales_invoice
from zatca_integration.saudi_arabia_electronic_invoicing.phase_one_utils import create_qr_code


class LegacyInvoice:
    """Small document double used to prove all ZATCA routes stop before side effects."""

    custom_is_legacy_import = 1
    custom_is_zatca_test = 0
    company = "Test Company"
    customer = "Test Customer"
    docstatus = 1
    taxes_and_charges = None

    def get(self, key, default=None):
        return getattr(self, key, default)


class TestLegacyImport(FrappeTestCase):
    def test_legacy_invoice_skips_submit_validation(self):
        validate_sales_invoice(LegacyInvoice(), None)

    @patch("zatca_integration.clearence_util.frappe.get_doc")
    def test_central_generation_guard_has_no_side_effects(self, get_doc):
        generate_einvoice(LegacyInvoice())
        get_doc.assert_not_called()

    @patch("zatca_integration.clearence_util.generate_einvoice")
    def test_submit_and_background_routes_skip_legacy_invoice(self, generate):
        doc = LegacyInvoice()
        generate_einvoice_on_submit(doc)
        bg_generate_einvoice(doc)
        generate.assert_not_called()

    @patch("zatca_integration.clearence_util.frappe.get_doc")
    def test_clearance_enforcement_skips_legacy_invoice(self, get_doc):
        enforce_b2b_clearance_on_submit(LegacyInvoice())
        get_doc.assert_not_called()

    @patch("zatca_integration.saudi_arabia_electronic_invoicing.phase_one_utils.frappe.get_doc")
    def test_phase_one_qr_skips_legacy_invoice(self, get_doc):
        create_qr_code(LegacyInvoice())
        get_doc.assert_not_called()

    def test_manual_resend_returns_explicit_legacy_skip(self):
        result = resend_einvoice(LegacyInvoice())
        self.assertTrue(result["skipped"])

    @patch("zatca_integration.clearence_util.frappe.has_permission", return_value=True)
    @patch("zatca_integration.clearence_util.frappe.get_doc", return_value=LegacyInvoice())
    def test_bulk_resend_reports_legacy_skip(self, get_doc, has_permission):
        result = bulk_resend_einvoices(["LEGACY-SINV-0001"])
        self.assertEqual(result["success"], [])
        self.assertEqual(result["failed"], [])
        self.assertEqual(result["skipped"][0]["name"], "LEGACY-SINV-0001")
        self.assertIn("Legacy import", result["skipped"][0]["message"])
