import json

import frappe
from frappe import _
from frappe.utils import flt

from erpnext.stock.doctype.pick_list.pick_list import create_stock_entry as make_outward_stock_entry


@frappe.whitelist()
def get_pick_lists():
    """Return open Pick Lists for the logged-in Picker's active warehouse."""

    if "Picker" not in frappe.get_roles(frappe.session.user):
        frappe.throw(_("Only users with Picker role can access Pick Lists."))

    active_warehouse = frappe.db.get_value(
        "Employee",
        {"user_id": frappe.session.user},
        "active_warehouse",
    )

    if not active_warehouse:
        frappe.throw(_("Active Warehouse is not set for the user."))

    pick_lists = frappe.get_all(
        "Pick List",
        filters={
            "docstatus": 1,
            "status": "Open",
            "source_warehouse": active_warehouse,
        },
        order_by="modified desc",
    )

    if not pick_lists:
        return {"data": []}

    pick_list_names = [row.name for row in pick_lists]

    packing_lists = frappe.get_all(
        "Packing List",
        filters={
            "pick_list": ["in", pick_list_names],
        },
        fields=["name", "pick_list", "docstatus"],
        order_by="creation desc",
    )

    packing_list_map = {}

    for row in packing_lists:
        if row.pick_list not in packing_list_map:
            packing_list_map[row.pick_list] = row

    result = []

    for pick_list in pick_lists:
        packing_list = packing_list_map.get(pick_list.name)

        if packing_list and packing_list.docstatus == 1:
            continue

        pick_list["packing_list"] = (
            packing_list.name if packing_list else None
        )
        pick_list["status"] = (
            "In Progress" if packing_list else "To Start"
        )

        result.append(pick_list)

    return {"data": result}


@frappe.whitelist()
def get_pick_list_items(pick_list):
    """Return Pick List items with packed qty."""

    packing_list = frappe.db.get_value(
        "Packing List",
        {
            "pick_list": pick_list,
        },
        "name",
        order_by="creation desc",
    )

    items = frappe.get_all(
        "Pick List Item",
        filters={
            "parent": pick_list,
            "parenttype": "Pick List",
            "parentfield": "locations",
        },
        fields=[
            "name",
            "item_code",
            "item_name",
            "qty",
            "picked_qty",
            "packed_qty",
            "uom",
        ],
        order_by="idx asc",
    )

    return {
        "packing_list": packing_list,
        "data": items,
    }


@frappe.whitelist()
def create_packing_box(data=None):
    if isinstance(data, str):
        data = json.loads(data)

    data = data or frappe.form_dict

    pick_list_id = data.get("pick_list")
    items = data.get("items") or []
    box_id = data.get("box_id")

    if frappe.db.exists("Box", {"box_id": box_id}):
        frappe.throw(
            _("Box label {0} already exists. Please use a different label.").format(box_id)
        )

    pick_list = frappe.get_doc("Pick List", pick_list_id)

    outward_warehouse = frappe.db.get_value(
        "Warehouse",
        {
            "main_warehouse": pick_list.source_warehouse,
            "is_sub_warehouse": 1,
            "warehouse_type": "Outward",
            "is_group": 0,
        },
        "name",
    )

    if not outward_warehouse:
        frappe.throw(
            _("Outward Warehouse not found for Source Warehouse {0}.").format(
                pick_list.source_warehouse
            )
        )

    packing_list_name = frappe.db.exists(
        "Packing List",
        {
            "pick_list": pick_list.name,
            "docstatus": 0,
        },
    )

    if packing_list_name:
        packing_list = frappe.get_doc("Packing List", packing_list_name)
    else:
        # First box: create the draft Packing List automatically.
        packing_list = frappe.new_doc("Packing List")
        packing_list.pick_list = pick_list.name
        packing_list.material_request = pick_list.material_request
        packing_list.company = pick_list.company
        packing_list.outward_warehouse = outward_warehouse
        packing_list.insert(ignore_permissions=True)

    # ---------------------------------------------------------
    # Create Box
    # ---------------------------------------------------------
    box = frappe.new_doc("Box")
    box.set("items", [])

    box.box_id = box_id
    box.packing_list = packing_list.name

    for item in items:
        item_code = item.get("item_code")
        qty = flt(item.get("qty"))

        box.append(
            "items",
            {
                "item": item_code,
                "qty": qty,
                "uom": item.get("uom"),
            },
        )

    box.total_items = len(box.items)
    box.insert(ignore_permissions=True)

    return {
        "packing_list": packing_list.name,
        "box_id": box.box_id,
        "status": "Draft",
    }


@frappe.whitelist()
def complete_packing_list(data=None):
    if isinstance(data, str):
        data = json.loads(data)

    data = data or frappe.form_dict

    packing_list_name = data.get("packing_list")
    packing_list = frappe.get_doc("Packing List", packing_list_name)

    if packing_list.docstatus == 1:
        return {
            "packing_list": packing_list.name,
            "status": "Submitted",
        }

    pick_list = frappe.get_doc("Pick List", packing_list.pick_list)

    # ---------------------------------------------------------
    # Prevent duplicate Outward Stock Entry
    # ---------------------------------------------------------
    existing = frappe.db.exists(
        "Stock Entry",
        {
            "packing_list": packing_list.name,
            "docstatus": 1,
            "add_to_transit": 0,
        },
    )

    if existing:
        stock_entry = frappe.get_doc("Stock Entry", existing)
    else:
        # -----------------------------------------------------
        # Create Outward Stock Entry from Pick List
        # -----------------------------------------------------
        stock_entry = frappe.get_doc(
            make_outward_stock_entry(
                frappe.as_json(pick_list.as_dict())
            )
        )

        stock_entry.pick_list = pick_list.name
        stock_entry.material_request = pick_list.material_request
        stock_entry.from_warehouse = pick_list.source_warehouse
        stock_entry.destination_warehouse = pick_list.destination_warehouse
        stock_entry.to_warehouse = packing_list.outward_warehouse
        stock_entry.add_to_transit = 0

        boxes = frappe.get_all(
            "Box",
            filters={
                "packing_list": packing_list.name,
                "docstatus": 0,
            },
            pluck="name",
        )

        packing_qty = {}

        if boxes:
            box_items = frappe.get_all(
                "Box Items",
                filters={
                    "parent": ["in", boxes],
                    "parenttype": "Box",
                    "parentfield": "items",
                },
                fields=[
                    "item",
                    "qty",
                ],
            )

            for item in box_items:
                packing_qty[item.item] = (
                    packing_qty.get(item.item, 0) + flt(item.qty)
                )

        for row in stock_entry.items:
            qty = packing_qty.get(row.item_code)

            if qty:
                row.qty = qty
                row.transfer_qty = qty
                row.s_warehouse = pick_list.source_warehouse
                row.t_warehouse = packing_list.outward_warehouse

        stock_entry.insert(ignore_permissions=True)
        stock_entry.submit()

    packing_list.submit()

    return {
        "packing_list": packing_list.name,
        "stock_entry": stock_entry.name,
        "status": "Submitted",
    }