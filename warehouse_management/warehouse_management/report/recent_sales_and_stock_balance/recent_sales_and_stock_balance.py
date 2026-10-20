# Copyright (c) 2026, Rakonex and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import add_days, getdate, today

def execute(filters=None):
    """Execute the Recent Sales and Stock Balance report."""

    filters = frappe._dict(filters or {})
    validate_filters(filters)

    active_warehouse, valid_warehouses = get_warehouse_context()

    other_warehouses = [
        warehouse
        for warehouse in valid_warehouses
        if warehouse != active_warehouse
    ]

    columns = get_columns(other_warehouses)

    data = get_data(
        filters,
        active_warehouse,
        valid_warehouses,
        other_warehouses,
    )

    return columns, data

def validate_filters(filters):
    """Set default dates and validate the selected date range."""

    if not filters.get("from_date"):
        filters.from_date = add_days(today(), -1)

    if not filters.get("to_date"):
        filters.to_date = today()

    filters.from_date = getdate(filters.from_date)
    filters.to_date = getdate(filters.to_date)

    if filters.from_date > filters.to_date:
        frappe.throw(_("From Date cannot be after To Date."))

def get_warehouse_context():
    """Get Storage warehouses and handle System Manager access."""

    is_system_manager = "System Manager" in frappe.get_roles(
        frappe.session.user
    )

    employee = frappe.db.get_value(
        "Employee",
        {
            "user_id": frappe.session.user,
            "status": "Active",
        },
        ["name", "active_warehouse"],
        as_dict=True,
    )

    active_warehouse = employee.active_warehouse if employee else None

    if not is_system_manager:
        if not employee:
            frappe.throw(
                _("No active Employee found for the logged-in user.")
            )

        if not active_warehouse:
            frappe.throw(
                _("Please set Active Warehouse in the Employee record.")
            )

    valid_warehouses = frappe.get_all(
        "Warehouse",
        filters={
            "disabled": 0,
            "is_group": 0,
            "warehouse_type": "Storage",
        },
        pluck="name",
        order_by="name asc",
        ignore_permissions=True,
    )

    if is_system_manager:
        if not active_warehouse:
            active_warehouse = (
                valid_warehouses[0] if valid_warehouses else None
            )

        return active_warehouse, valid_warehouses

    if active_warehouse not in valid_warehouses:
        frappe.throw(
            _("The employee's Active Warehouse must have "
              "Warehouse Type = Storage.")
        )

    return active_warehouse, valid_warehouses

def get_columns(other_warehouses):
    """Create fixed columns and one stock column per other warehouse."""

    columns = [
        {
            "label": _("Item"),
            "fieldname": "item_code",
            "fieldtype": "Link",
            "options": "Item",
            "width": 220,
        },
        {
            "label": _("Warehouse"),
            "fieldname": "warehouse",
            "fieldtype": "Link",
            "options": "Warehouse",
            "width": 200,
        },
        {
            "label": _("Current Stock"),
            "fieldname": "current_stock",
            "fieldtype": "Float",
            "width": 130,
        },
        {
            "label": _("Stock UOM"),
            "fieldname": "stock_uom",
            "fieldtype": "Link",
            "options": "UOM",
            "width": 120,
        },
    ]

    for index, warehouse in enumerate(other_warehouses, start=1):
        columns.append(
            {
                "label": _("Stock in {0}").format(warehouse),
                "fieldname": f"stock_in_warehouse_{index}",
                "fieldtype": "Float",
                "width": 170,
            }
        )

    return columns


def get_data(
    filters,
    active_warehouse,
    valid_warehouses,
    other_warehouses,
):
    """Show recent-sales items with their current stock per warehouse."""

    # 1. Find items sold during the selected date range.
    sales_invoices = frappe.get_all(
        "Sales Invoice",
        filters={
            "docstatus": 1,
            "is_return": 0,
            "posting_date": [
                "between",
                [filters.from_date, filters.to_date],
            ],
        },
        pluck="name",
    )

    if not sales_invoices:
        return []

    # Fetch items belonging to those invoices.
    sales_rows = frappe.get_all(
        "Sales Invoice Item",
        filters={
            "parent": ["in", sales_invoices],
        },
        fields=["item_code"],
        distinct=True,
    )

    # Remove empty item codes and sort the unique items.
    sold_items = sorted(
        {
            row.item_code
            for row in sales_rows
            if row.item_code
        }
    )

    if not sold_items:
        return []
    
    # 2. Get current stock for these items in all selected warehouses.
    stock_rows = frappe.get_all(
        "Bin",
        filters={
            "item_code": ["in", sold_items],
            "warehouse": ["in", valid_warehouses],
        },
        fields=[
            "item_code",
            "warehouse",
            "actual_qty",
        ],
        order_by="item_code asc, warehouse asc",
    )

    # 3. Initialize every sold item with zero stock in every warehouse.
    stock_map = {
        item_code: {
            warehouse: 0
            for warehouse in valid_warehouses
        }
        for item_code in sold_items
    }

    # 4. Replace zero with actual stock wherever a Bin record exists.
    for stock in stock_rows:
        stock_map[stock.item_code][stock.warehouse] = (
            stock.actual_qty or 0
        )

    # 5. Get the stock UOM for enabled items.
    item_rows = frappe.get_all(
        "Item",
        filters={
            "name": ["in", sold_items],
            "disabled": 0,
        },
        fields=[
            "name",
            "stock_uom",
        ],
    )

    uom_map = {
        item.name: item.stock_uom
        for item in item_rows
    }

    # 6. Build the report rows.
    data = []

    for item_code in sold_items:
        # Preserve the existing behavior of excluding disabled items.
        if item_code not in uom_map:
            continue

        warehouse_stock = stock_map[item_code]

        row = {
            "item_code": item_code,
            "warehouse": active_warehouse,
            "current_stock": warehouse_stock.get(
                active_warehouse, 0
            ),
            "stock_uom": uom_map[item_code],
        }

        # Show the actual quantity for each other warehouse.
        # If no stock exists there, show zero.
        for index, warehouse in enumerate(
            other_warehouses, start=1
        ):
            row[f"stock_in_warehouse_{index}"] = (
                warehouse_stock.get(warehouse, 0)
            )

        data.append(row)

    return data