import frappe


def get_sub_warehouses(warehouse, include_sub_warehouses=True):
    """
    Return warehouses managed by the selected warehouse.
    """

    if not warehouse:
        return []

    warehouse_data = frappe.db.get_value(
        "Warehouse",
        warehouse,
        ["is_sub_warehouse", "disabled"],
        as_dict=True,
    )

    if (
        not warehouse_data
        or warehouse_data.disabled
        or warehouse_data.is_sub_warehouse
    ):
        return []

    warehouses = [warehouse]

    if include_sub_warehouses:
        warehouses.extend(
            frappe.get_all(
                "Warehouse",
                filters={
                    "main_warehouse": warehouse,
                    "is_sub_warehouse": 1,
                    "disabled": 0,
                },
                pluck="name",
            )
        )

    return warehouses


def get_main_warehouse(warehouse):
    """
    Return the main warehouse responsible for the warehouse.
    """

    if not warehouse:
        return None

    data = frappe.db.get_value(
        "Warehouse",
        warehouse,
        ["is_sub_warehouse", "main_warehouse", "disabled"],
        as_dict=True,
    )

    if not data or data.disabled:
        return None

    return data.main_warehouse if data.is_sub_warehouse else warehouse


def get_warehouse_managers(warehouse):
    manager_warehouse = get_main_warehouse(warehouse)

    if not manager_warehouse:
        return []

    employees = frappe.get_all(
        "Employee",
        filters={
            "active_warehouse": manager_warehouse,
            "status": "Active",
        },
        fields=["user_id"],
    )

    managers = []

    for employee in employees:
        if not employee.user_id:
            continue

        if "Warehouse Manager" in frappe.get_roles(employee.user_id):
            managers.append(employee.user_id)

    return list(set(managers))