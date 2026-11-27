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

        # Get the QC Passed Storage Bin.
        passed_bin = frappe.db.get_value(
            "Storage Bin",
            {"warehouse": self.warehouse, "is_flagged": 0, "is_default": 1},
            ["name", "rack"],
            as_dict=True,
        )

        # Get the Flagged Storage Bin.
        flagged_bin = frappe.db.get_value(
            "Storage Bin",
            {"warehouse": self.warehouse, "is_flagged": 1, "is_default": 1},
            ["name", "rack"],
            as_dict=True,
        )

        for row in self.items:
            for qty, storage_bin, bin_type in [
                (flt(row.qc_passed_qty), passed_bin, "QC Passed"),
                (flt(row.flagged_qty), flagged_bin, "Flagged"),
            ]:
                if qty <= 0:
                    continue

                if not storage_bin:
                    frappe.throw(
                        _("{0} Storage Bin not found for Bay Warehouse {1}.").format(
                            bin_type, self.warehouse
                        )
                    )

                frappe.get_doc({
                    "doctype": "Bin Assignment",
                    "assignment_type": "Placing",
                    "item": row.item,
                    "rack": storage_bin.rack,
                    "bin": storage_bin.name,
                    "quantity": qty,
                    "uom": row.uom,
                    "material_request": self.material_request,
                    "pick_list": self.pick_list,
                    "notes": f"{bin_type} verification completed for {self.name}",
                }).insert(ignore_permissions=True)
        