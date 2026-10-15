import frappe
from frappe.query_builder import DocType
from pypika.functions import Coalesce

from warehouse_management.utils import get_main_warehouse


def check_critical_stock():
    Item = DocType("Item")
    ItemReorder = DocType("Item Reorder")
    Bin = DocType("Bin")
    Warehouse = DocType("Warehouse")

    rows = (
        frappe.qb.from_(ItemReorder)
        .inner_join(Item)
        .on(Item.name == ItemReorder.parent)
        .inner_join(Warehouse)
        .on(Warehouse.name == ItemReorder.warehouse)
        .left_join(Bin)
        .on(
            (Bin.item_code == Item.name)
            & (Bin.warehouse == ItemReorder.warehouse)
        )
        .select(
            Item.name.as_("item_code"),
            Item.item_name,
            ItemReorder.warehouse,
            ItemReorder.warehouse_reorder_level.as_("critical_qty"),
            Coalesce(Bin.actual_qty, 0).as_("current_stock"),
        )
        .where(Item.disabled == 0)
        .where(Warehouse.disabled == 0)
        .where(Warehouse.is_sub_warehouse == 0)
        .where(
            Coalesce(Bin.actual_qty, 0)
            <= ItemReorder.warehouse_reorder_level
        )
        .run(as_dict=True)
    )

    manager_data = {}

    for row in rows:
        manager_warehouse = get_main_warehouse(row["warehouse"])

        if not manager_warehouse:
            continue

        manager_data.setdefault(
            manager_warehouse,
            [],
        ).append(row)

    for manager_warehouse, items in manager_data.items():
        send_notification(manager_warehouse, items)


def send_notification(manager_warehouse, items):
    employees = frappe.get_all(
        "Employee",
        filters={
            "status": "Active",
            "active_warehouse": manager_warehouse,
        },
        fields=["user_id"],
    )

    if not employees:
        return

    lines = [
        "The following items are below critical stock:",
        "",
    ]

    for item in items:
        lines.append(
            f"• <b>{item['item_code']}</b> "
            f"(Current: {item['current_stock']}, "
            f"Critical: {item['critical_qty']})"
        )

    message = "<br>".join(lines)

    for employee in employees:
        if not employee.user_id:
            continue

        roles = frappe.get_roles(employee.user_id)

        if "Warehouse Manager" not in roles:
            continue

        if "System Manager" in roles:
            continue

        frappe.get_doc(
            {
                "doctype": "Notification Log",
                "subject": f"Stock Replenishment Required for {manager_warehouse}",
                "email_content": message,
                "for_user": employee.user_id,
                "type": "Alert",
            }
        ).insert(ignore_permissions=True)