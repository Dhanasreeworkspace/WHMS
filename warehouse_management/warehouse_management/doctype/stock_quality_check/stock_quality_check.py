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

        # Get Bay Storage Bin for the verification warehouse.
        bay_bin = frappe.db.get_value(
            "Storage Bin",
            {"warehouse": self.warehouse},
            ["name", "rack"],
            as_dict=True,
        )

        if not bay_bin:
            frappe.throw(
                _("Storage Bin not found for Bay Warehouse {0}.").format(
                    self.warehouse
                )
            )

        # Aggregate verified quantities by item.
        items = {}

        for row in self.items:
            if row.item not in items:
                items[row.item] = {
                    "qty": 0,
                    "uom": row.uom,
                }

            items[row.item]["qty"] += flt(row.verified_qty)

        # Create Placing Bin Assignments in Bay.
        for item_code, item_data in items.items():
            if item_data["qty"] <= 0:
                continue

            frappe.get_doc({
                "doctype": "Bin Assignment",
                "assignment_type": "Placing",
                "item": item_code,
                "rack": bay_bin.rack,
                "bin": bay_bin.name,
                "quantity": item_data["qty"],
                "uom": item_data["uom"],
                "notes": f"Verification completed for {self.name}",
            }).insert(ignore_permissions=True)