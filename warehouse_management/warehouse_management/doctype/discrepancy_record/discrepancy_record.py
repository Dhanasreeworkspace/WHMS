# Copyright (c) 2026, Rakonex and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt
from frappe.model.document import Document
from warehouse_management.utils import get_warehouse_managers


class DiscrepancyRecord(Document):
	pass


@frappe.whitelist()
def create_discrepancy_record(data):
    """
    Create a Discrepancy Record from Picking or Packing.
    """

    if isinstance(data, str):
        data = frappe.parse_json(data)

    discrepancy_process = data.get("discrepancy_process")
    discrepancy_type = data.get("discrepancy_type")
    priority = data.get("priority")
    item_code = data.get("item_code")
    affected_qty = data.get("affected_qty")
    uom = data.get("uom")
    warehouse = data.get("warehouse")

    rack = data.get("rack")
    bin = data.get("bin")
    box = data.get("box")

    remarks = data.get("remarks")
    photo = data.get("photo")

    if rack:
        rack_warehouse = frappe.db.get_value("Rack", rack, "warehouse")

        if rack_warehouse != warehouse:
            frappe.throw(
                _("Rack {0} belongs to warehouse {1}, not {2}.").format(
                    rack,
                    rack_warehouse,
                    warehouse,
                )
            )

    if bin:
        bin_warehouse = frappe.db.get_value("Storage Bin", bin, "warehouse")

        if bin_warehouse != warehouse:
            frappe.throw(
                _("Storage Bin {0} belongs to warehouse {1}, not {2}.").format(
                    bin,
                    bin_warehouse,
                    warehouse,
                )
            )

    doc = frappe.new_doc("Discrepancy Record")

    doc.discrepancy_process = discrepancy_process
    doc.discrepancy_type = discrepancy_type
    doc.priority = priority

    doc.item_code = item_code
    doc.affected_qty = flt(affected_qty)
    doc.uom = uom
    doc.warehouse = warehouse
    doc.rack = rack
    doc.bin = bin
    doc.box = box

    doc.remarks = remarks
    doc.photo = photo

    doc.insert()
    managers = notify_warehouse_managers(doc)

    return {
        "status": "success",
        "message": "Discrepancy Record created successfully",
        "data": doc.name,
        "managers": managers,
    }


def notify_warehouse_managers(discrepancy):
    managers = get_warehouse_managers(discrepancy.warehouse)

    if not managers:
        frappe.log_error(
            title="Warehouse Manager Not Found",
            message=(
                f"No Warehouse Manager found for warehouse "
                f"{discrepancy.warehouse}. "
                f"Discrepancy: {discrepancy.name}"
            ),
        )
        return []

    for manager in managers:
        frappe.get_doc(
            {
                "doctype": "Notification Log",
                "for_user": manager,
                "type": "Alert",
                "document_type": "Discrepancy Record",
                "document_name": discrepancy.name,
                "subject": (
                    f"{discrepancy.discrepancy_process} Discrepancy - "
                    f"{discrepancy.discrepancy_type}"
                ),
                "email_content": (
                    f"Item: {discrepancy.item_code}<br>"
                    f"Quantity: {discrepancy.affected_qty} "
                    f"{discrepancy.uom or ''}"
                ),
            }
        ).insert(ignore_permissions=True)

    return managers