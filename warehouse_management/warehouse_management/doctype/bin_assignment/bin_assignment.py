# Copyright (c) 2026, Rakonex and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt


class BinAssignment(Document):

    def validate(self):
        if not self.bin or not self.item:
            return

        storage_bin = frappe.get_doc("Storage Bin", self.bin)

        item_row = next(
            (row for row in storage_bin.items if row.item == self.item),
            None
        )

        self.replaced_bin_assignment = (
            item_row.bin_assignment_record if item_row else None
        )

        if self.assignment_type == "Picking":
            if not item_row:
                frappe.throw(
                    f"Item {self.item} is not available in "
                    f"Storage Bin {self.bin}."
                )

            available_qty = flt(item_row.quantity)
            requested_qty = abs(flt(self.quantity))

            if requested_qty <= 0:
                frappe.throw("Picking quantity must be greater than zero.")

            if requested_qty > available_qty:
                frappe.throw(
                    f"Insufficient quantity for Item {self.item} "
                    f"in Storage Bin {self.bin}. "
                    f"Available: {available_qty}, "
                    f"Requested: {requested_qty}"
                )

    def after_insert(self):
        if not self.bin or not self.item:
            return

        storage_bin = frappe.get_doc("Storage Bin", self.bin)

        item_row = next(
            (row for row in storage_bin.items if row.item == self.item),
            None
        )

        qty = abs(flt(self.quantity))

        if qty <= 0:
            frappe.throw("Assignment quantity must be greater than zero.")

        if self.assignment_type == "Placing":

            if item_row:
                item_row.quantity = flt(item_row.quantity) + qty
                item_row.uom = self.uom
                item_row.assigned_date = self.doa

            else:
                item_row = storage_bin.append(
                    "items",
                    {
                        "item": self.item,
                        "item_name": self.item_name,
                        "quantity": qty,
                        "uom": self.uom,
                        "assigned_date": self.doa,
                    }
                )

        elif self.assignment_type == "Picking":

            if not item_row:
                frappe.throw(
                    f"Item {self.item} is not available in "
                    f"Storage Bin {self.bin}."
                )

            item_row.quantity = max(
                flt(item_row.quantity) - qty,
                0
            )

        item_row.bin_assignment_record = self.name
        storage_bin.save(ignore_permissions=True)

    def after_delete(self):
        if not self.bin or not self.item:
            return

        storage_bin = frappe.get_doc("Storage Bin", self.bin)

        assignments = frappe.get_all(
            "Bin Assignment",
            filters={
                "bin": self.bin,
                "item": self.item,
            },
            fields=[
                "name",
                "assignment_type",
                "quantity",
                "uom",
                "doa",
                "creation",
            ],
            order_by="creation asc",
        )

        balance = 0

        for assignment in assignments:
            qty = abs(flt(assignment.quantity))

            if assignment.assignment_type == "Placing":
                balance += qty

            elif assignment.assignment_type == "Picking":
                balance -= qty

        if balance < -0.000001:
            frappe.throw(
                f"Cannot reverse Bin Assignment {self.name}. "
                "Remaining picking quantity exceeds placing quantity."
            )

        item_row = next(
            (row for row in storage_bin.items if row.item == self.item),
            None
        )

        # Keep the item row even when its quantity becomes zero.
        if not item_row:
            item_row = storage_bin.append(
                "items",
                {
                    "item": self.item,
                    "item_name": frappe.db.get_value(
                        "Item", self.item, "item_name"
                    ),
                    "quantity": 0,
                }
            )

        item_row.quantity = max(balance, 0)

        # Find the latest remaining assignment for this item in this bin.
        latest_assignment = assignments[-1] if assignments else None

        item_row.bin_assignment_record = (
            latest_assignment.name if latest_assignment else None
        )

        # Restore the latest Placing assignment's details.
        latest_placing = next(
            (
                assignment for assignment in reversed(assignments)
                if assignment.assignment_type == "Placing"
            ),
            None
        )

        if latest_placing:
            item_row.uom = latest_placing.uom
            item_row.assigned_date = latest_placing.doa

        storage_bin.save(ignore_permissions=True)


def create_bin_assignments_on_purchase_receipt_submit(doc, method):
	"""Create Bin Assignment records for Purchase Receipt items that have rack and bin assigned"""
	for item in doc.items:
		if item.get("rack") and item.get("bin"):
			# Create Bin Assignment
			bin_assignment = frappe.get_doc({
				"doctype": "Bin Assignment",
				"assignment_type": "Placing",
				"purchase_receipt": doc.name,
				"item": item.item_code,
				"rack": item.rack,
				"bin": item.bin,
				"uom": item.uom,
				"quantity": item.qty,
				"expiry_date": item.get("expiry_date"),
				"doa": item.get("date_of_assignment"),
				"batch_no": item.get("batch_no"),
				"notes": f"Auto-created from Purchase Receipt {doc.name}"
			})
			bin_assignment.insert(ignore_permissions=True)


def delete_bin_assignments_on_purchase_receipt_cancel(doc, method=None):

	bin_assignments = frappe.get_all(
		"Bin Assignment",
		filters={
			"purchase_receipt": doc.name
		},
		pluck="name"
	)

	for name in bin_assignments:
		frappe.delete_doc(
            "Bin Assignment",
            name,
            ignore_permissions=True
        )