import frappe
from frappe import _


def validate_warehouse_type(doc, method=None):
    """ Validates the warehouse type based on the following rules:
    1. Sub warehouses cannot be marked as Storage.
    2. Main warehouses cannot be marked as Bay or Hold.
    3. If the warehouse type is Bay or Storage, include_in_transaction is set to 1.
    4. Only one Outward warehouse is allowed under a main warehouse.
    """
    
    # External Warehouse validations
    if doc.get("external"):

        if doc.is_sub_warehouse:
            frappe.throw(
                _("External warehouses cannot be Sub Warehouses.")
            )

        if doc.get("main_warehouse"):
            frappe.throw(
                _("External warehouses must have Main Warehouse empty.")
            )

        if doc.warehouse_type != "Consignment":
            frappe.throw(
                _("External warehouses must have Warehouse Type Consignment.")
            )

    if doc.is_sub_warehouse and doc.warehouse_type == "Storage":
        frappe.throw(
            _("Sub warehouses cannot be marked as Storage")
        )

    if not doc.is_sub_warehouse and doc.warehouse_type in ["Bay", "Hold"]:
        frappe.throw(
            _("Main warehouses cannot be marked as Bay or Hold")
        )

    if doc.warehouse_type in ["Bay", "Storage"]:
        doc.include_in_transaction = 1

    # Only one Outward warehouse is allowed under a main warehouse
    if doc.is_sub_warehouse and doc.warehouse_type == "Outward":
        existing_outward = frappe.db.exists(
            "Warehouse",
            {
                "main_warehouse": doc.main_warehouse,
                "warehouse_type": "Outward",
                "is_sub_warehouse": 1,
                "name": ["!=", doc.name],
            },
        )

        if existing_outward:
            frappe.throw(
                _("Only one Outward warehouse is allowed per main warehouse.")
            )