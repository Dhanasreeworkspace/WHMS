# Copyright (c) 2026, Rakonex and Contributors
# See license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class StockQualityCheck(Document):

    def validate(self):
        self.total_verified = 0
        self.total_qc_passed = 0

        for row in self.items:
            self.total_verified += flt(row.verified_qty)
            self.total_qc_passed += flt(row.qc_passed_qty)

    def on_submit(self):
        if self.packing_list:
            frappe.db.set_value(
                "Packing List",
                self.packing_list,
                "stock_status",
                "Verified",
                update_modified=True,
            )