# Copyright (c) 2026, Rakonex and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import parse_json
from frappe.query_builder import DocType

from warehouse_management.utils import get_sub_warehouses


def execute(filters=None):
    """Build the Stock Replenishment Report with warehouse-wise stock columns.
    Restricted warehouse managers see their active warehouse and other warehouses with available stock.
    """
    filters = filters or {}

    data, comparison_warehouses = get_data(filters)
    columns = get_columns(comparison_warehouses)

    return columns, data


def get_columns(comparison_warehouses=None):
    columns = [
        {
            "label": "Item",
            "fieldname": "item_code",
            "fieldtype": "Link",
            "options": "Item",
            "width": 200,
        },
        {
            "label": "Warehouse",
            "fieldname": "warehouse",
            "fieldtype": "Link",
            "options": "Warehouse",
            "width": 180,
        },
        {
            "label": "Current Stock",
            "fieldname": "current_stock",
            "fieldtype": "Float",
            "width": 120,
        },
        {
            "label": "Critical Qty",
            "fieldname": "critical_qty",
            "fieldtype": "Float",
            "width": 120,
        },
        {
            "label": "Reorder Qty",
            "fieldname": "reorder_qty",
            "fieldtype": "Float",
            "width": 120,
        },
        {
            "label": "Stock UOM",
            "fieldname": "stock_uom",
            "fieldtype": "Link",
            "options": "UOM",
            "width": 120,
        },
    ]

    for warehouse in comparison_warehouses or []:
        columns.append(
            {
                "label": f"Stock in {warehouse.warehouse_name or warehouse.name}",
                "fieldname": f"stock_{frappe.scrub(warehouse.name)}",
                "fieldtype": "Float",
                "width": 150,
            }
        )

    return columns


def get_data(filters):
    """Fetch replenishment items and calculate stock for main warehouses and sub-warehouses.
    Transit and Hold warehouses are excluded from all stock calculations.
    """
    Item = DocType("Item")
    ItemReorder = DocType("Item Reorder")
    Warehouse = DocType("Warehouse")

    query = (
        frappe.qb.from_(ItemReorder)
        .inner_join(Item)
        .on(Item.name == ItemReorder.parent)
        .inner_join(Warehouse)
        .on(Warehouse.name == ItemReorder.warehouse)
        .select(
            Item.name.as_("item_code"),
            Item.item_name,
            Item.stock_uom,
            ItemReorder.warehouse,
            ItemReorder.warehouse_reorder_level.as_("critical_qty"),
            ItemReorder.warehouse_reorder_qty.as_("reorder_qty"),
        )
        .where(Item.disabled == 0)
        .where(Warehouse.disabled == 0)
        .where(Warehouse.is_sub_warehouse == 0)
        .where(Warehouse.include_in_transaction == 1)
    )

    roles = frappe.get_roles(frappe.session.user)

    employee = None

    if "System Manager" in roles:
        pass

    elif "Warehouse Manager" in roles:
        employee = get_employee_details()

        if not employee:
            return [], []

        if not employee.allow_access_to_all_warehouses:
            if not employee.active_warehouse:
                return [], []

            allowed_warehouses = get_sub_warehouses(employee.active_warehouse)

            if not allowed_warehouses:
                return [], []

            query = query.where(
                ItemReorder.warehouse.isin(allowed_warehouses)
            )
    else:
        return [], []

    if filters.get("warehouse"):
        warehouses = get_sub_warehouses(filters["warehouse"])

        if not warehouses:
            return [], []

        query = query.where(
            ItemReorder.warehouse.isin(warehouses)
        )

    rows = query.run(as_dict=True)

    if not rows:
        return [], []

    current_warehouse = get_current_warehouse(filters, employee, roles)

    if (
        "Warehouse Manager" in roles
        and employee
        and not employee.allow_access_to_all_warehouses
    ):
        current_warehouse = employee.active_warehouse

    item_codes = {
        row["item_code"]
        for row in rows
        if row.get("item_code")
    }

    report_warehouses = {
        row["warehouse"]
        for row in rows
        if row.get("warehouse")
    }

    stock_map = get_warehouse_stock(item_codes, report_warehouses)

    for row in rows:
        row["current_stock"] = stock_map.get(
            (row["item_code"], row["warehouse"]),
            0,
        )

    if filters.get("critical_only"):
        rows = [
            row
            for row in rows
            if row["current_stock"] <= row["critical_qty"]
        ]

    if not rows:
        return [], []

    if (
        "System Manager" in roles
        or (
            employee
            and employee.allow_access_to_all_warehouses
        )
    ):
        return rows, []

    if not current_warehouse:
        return rows, []

    company = frappe.db.get_value("Warehouse", current_warehouse, "company")

    if not company:
        return rows, []

    other_warehouses = frappe.get_all(
        "Warehouse",
        filters={
            "company": company,
            "disabled": 0,
            "is_group": 0,
            "is_sub_warehouse": 0,
            "include_in_transaction": 1,
            "name": ["!=", current_warehouse],
        },
        fields=["name", "warehouse_name"],
        order_by="name",
    )

    if not other_warehouses:
        return rows, []

    other_warehouse_names = [
        warehouse.name
        for warehouse in other_warehouses
    ]

    comparison_stock_map = get_warehouse_stock(item_codes, other_warehouse_names)

    warehouses_with_stock = {
        warehouse
        for (item_code, warehouse), qty in comparison_stock_map.items()
        if qty > 0
    }

    comparison_warehouses = [
        warehouse
        for warehouse in other_warehouses
        if warehouse.name in warehouses_with_stock
    ]

    for row in rows:
        for warehouse in comparison_warehouses:
            row[f"stock_{frappe.scrub(warehouse.name)}"] = comparison_stock_map.get(
                (row["item_code"], warehouse.name), 0
            )

    return rows, comparison_warehouses


def get_employee_details():
    """Return the active employee's warehouse access settings.
    Returns the employee's active warehouse and all-warehouse access flag.
    """
    return frappe.db.get_value(
        "Employee",
        {
            "user_id": frappe.session.user,
            "status": "Active",
        },
        [
            "active_warehouse",
            "allow_access_to_all_warehouses",
        ],
        as_dict=True,
    )


def get_current_warehouse(filters, employee, roles):
    """Determine the warehouse used as the report's current warehouse.
    Uses the selected filter where applicable, otherwise the employee's active warehouse.
    """
    if filters.get("warehouse"):
        return filters["warehouse"]

    if (
        "Warehouse Manager" in roles
        and employee
        and not employee.allow_access_to_all_warehouses
    ):
        return employee.active_warehouse

    return None


def get_warehouse_stock(item_codes, warehouses):
    """Return stock totals grouped by item and main warehouse.
    Includes valid sub-warehouses while excluding Transit and Hold warehouses.
    """
    if not item_codes or not warehouses:
        return {}

    warehouse_groups = {}

    for warehouse in warehouses:
        managed_warehouses = get_sub_warehouses(warehouse)

        if managed_warehouses:
            warehouse_groups[warehouse] = managed_warehouses

    all_warehouse_names = {
        sub_warehouse
        for managed_warehouses in warehouse_groups.values()
        for sub_warehouse in managed_warehouses
    }

    if not all_warehouse_names:
        return {}

    warehouse_data = frappe.get_all(
        "Warehouse",
        filters={
            "name": ["in", list(all_warehouse_names)],
            "disabled": 0,
            "include_in_transaction": 1,
        },
        fields=[
            "name",
            "is_sub_warehouse",
            "main_warehouse",
        ],
    )

    valid_warehouses = {row.name for row in warehouse_data}

    bin_rows = frappe.get_all(
        "Bin",
        filters={
            "item_code": ["in", list(item_codes)],
            "warehouse": ["in", list(valid_warehouses)],
        },
        fields=["item_code", "warehouse", "actual_qty"],
    )

    warehouse_lookup = {}

    for main_warehouse, managed_warehouses in warehouse_groups.items():
        for warehouse in managed_warehouses:
            if warehouse in valid_warehouses:
                warehouse_lookup[warehouse] = main_warehouse

    stock_map = {}

    for row in bin_rows:
        main_warehouse = warehouse_lookup.get(row.warehouse)

        if not main_warehouse:
            continue

        key = (row.item_code, main_warehouse)
        stock_map[key] = stock_map.get(key, 0) + (row.actual_qty or 0)

    return stock_map


@frappe.whitelist()
def get_material_request(items):
    """Create a Material Transfer request from selected replenishment items.
    Sets the selected report warehouse as the target warehouse.
    """
    if isinstance(items, str):
        items = parse_json(items)

    target_warehouses = {
        row.get("warehouse")
        for row in items
        if row.get("warehouse")
    }

    target_warehouse = next(iter(target_warehouses))

    mr = frappe.new_doc("Material Request")
    mr.material_request_type = "Material Transfer"
    mr.set_warehouse = target_warehouse

    for row in items:
        mr.append(
            "items",
            {
                "item_code": row["item_code"],
                "warehouse": target_warehouse,
                "qty": row["reorder_qty"],
                "stock_uom": row["stock_uom"],
                "uom": row["stock_uom"],
            },
        )

    return mr.as_dict()


@frappe.whitelist()
def get_warehouse_query(doctype, txt, searchfield, start, page_len, filters):
    """Return warehouses available for the report warehouse filter.
    Restricted managers see their active warehouse, while unrestricted users see all warehouses.
    """
    roles = frappe.get_roles(frappe.session.user)

    if "System Manager" not in roles and "Warehouse Manager" not in roles:
        return []

    warehouse_filters = {
        "disabled": 0,
        "is_sub_warehouse": 0,
    }

    if "System Manager" not in roles:
        employee = get_employee_details()

        if not employee:
            return []

        if not employee.allow_access_to_all_warehouses:
            if not employee.active_warehouse:
                return []

            warehouse_filters["name"] = employee.active_warehouse

    if txt:
        warehouse_filters["name"] = ["like", f"%{txt}%"]

    warehouses = frappe.get_all(
        "Warehouse",
        filters=warehouse_filters,
        pluck="name",
        order_by="name",
        limit_start=start,
        limit_page_length=page_len,
    )

    return [(warehouse,) for warehouse in warehouses]