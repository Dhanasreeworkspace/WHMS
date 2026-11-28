import json

import frappe
from frappe import _
from frappe.utils import flt

from erpnext.stock.doctype.stock_entry.stock_entry import make_stock_in_entry


@frappe.whitelist()
def get_driver_packing_lists(source_warehouse):
    """Return submitted Packing Lists available for driver acceptance."""

    packing_lists = frappe.get_all(
        "Packing List",
        filters={
            "docstatus": 1,
            "source_warehouse": source_warehouse,
        },
        fields=[
            "name",
            "pick_list",
            "material_request",
            "is_consignment",
            "total_boxes",
            "source_warehouse",
            "destination_warehouse",
        ],
        order_by="modified desc",
    )

    pick_list_names = [row.pick_list for row in packing_lists if row.pick_list]

    transit_pick_lists = frappe.get_all(
        "Stock Entry",
        filters={
            "pick_list": ["in", pick_list_names],
            "add_to_transit": 1,
            "docstatus": 1,
        },
        pluck="pick_list",
    ) if pick_list_names else []

    transit_pick_lists = set(transit_pick_lists)

    result = [
        {
            "packing_list": row.name,
            "mr_id": row.material_request,
            "is_consignment": row.is_consignment,
            "total_boxes": row.total_boxes,
            "from_wh": row.source_warehouse,
            "to_wh": row.destination_warehouse,
        }
        for row in packing_lists
        if row.pick_list not in transit_pick_lists
    ]

    return {"data": result}


@frappe.whitelist()
def get_packing_list_details(packing_list):
    """Return Packing List details with total box count."""

    packing_list_doc = frappe.get_doc("Packing List", packing_list)

    boxes = frappe.get_all(
        "Box",
        filters={
            "packing_list": packing_list_doc.name,
        },
        fields=["name", "box_id", "total_items"],
        order_by="creation asc",
    )

    return {
        "packing_list": packing_list_doc.name,
        "is_consignment": packing_list_doc.is_consignment,
        "pick_list": packing_list_doc.pick_list,
        "total_boxes": packing_list_doc.total_boxes,
        "boxes": [
            {
                "box_label": box.box_id,
                "total_items": box.total_items,
            }
            for box in boxes
        ],
    }


@frappe.whitelist()
def create_stock_entry(data=None):
    """
    Create and submit Add-to-Transit Stock Entry.
    """

    if isinstance(data, str):
        data = json.loads(data)

    data = data or frappe.form_dict

    transit_wh = data.get("transit_wh")
    pick_list_id = data.get("pick_list")

    pick_list = frappe.get_doc("Pick List", pick_list_id)

    packing_list = frappe.get_doc(
        "Packing List",
        {
            "pick_list": pick_list.name,
            "docstatus": 1,
        },
    )

    stock_entry = frappe.new_doc("Stock Entry")

    stock_entry.update({
        "stock_entry_type": "Material Transfer",
        "purpose": "Material Transfer",
        "company": pick_list.company,
        "from_warehouse": packing_list.outward_warehouse,
        "to_warehouse": transit_wh,
        "destination_warehouse": pick_list.destination_warehouse,
        "pick_list": pick_list.name,
        "material_request": pick_list.material_request,
        "add_to_transit": 1,
        "is_consignment": pick_list.is_consignment,
    })

    for row in pick_list.locations:
        qty = flt(row.qty)

        if qty <= 0:
            continue

        stock_entry.append(
            "items",
            {
                "item_code": row.item_code,
                "item_name": row.item_name,
                "description": row.description,
                "qty": qty,
                "transfer_qty": qty,
                "uom": row.uom,
                "stock_uom": row.stock_uom,
                "conversion_factor": row.conversion_factor or 1,
                "s_warehouse": packing_list.outward_warehouse,
                "t_warehouse": transit_wh,
                "material_request_item": row.material_request_item,
            },
        )

    if not stock_entry.items:
        frappe.throw(
            _("No valid items found in Pick List {0}.")
            .format(pick_list.name)
        )

    stock_entry.insert(ignore_permissions=True)
    stock_entry.submit()

    return {
        "stock_entry": stock_entry.name,
        "material_request": pick_list.material_request,
        "from_warehouse": packing_list.outward_warehouse,
        "to_warehouse": transit_wh,
        "destination_warehouse": pick_list.destination_warehouse,
    }

@frappe.whitelist()
def get_driver_consignments(source_warehouse, vehicle):
    """Return in-transit Packing Lists of the driver"""

    packing_lists = frappe.get_all(
        "Packing List",
        filters={
            "docstatus": 1,
            "is_consignment": 1,
            "source_warehouse": source_warehouse,
        },
        fields=[
            "name",
            "pick_list",
            "material_request",
            "is_consignment",
            "total_boxes",
            "source_warehouse",
            "destination_warehouse",
        ],
        order_by="modified desc",
    )

    pick_list_names = [row.pick_list for row in packing_lists if row.pick_list]

    transit_pick_lists = frappe.get_all(
        "Stock Entry",
        filters={
            "pick_list": ["in", pick_list_names],
            "add_to_transit": 1,
            "to_warehouse": vehicle,
            "docstatus": 1,
        },
        pluck="pick_list",
    ) if pick_list_names else []

    transit_pick_lists = set(transit_pick_lists)

    result = [
        {
            "packing_list": row.name,
            "mr_id": row.material_request,
            "is_consignment": row.is_consignment,
            "total_boxes": row.total_boxes,
            "from_wh": row.source_warehouse,
            "to_wh": row.destination_warehouse,
        }
        for row in packing_lists
        if row.pick_list in transit_pick_lists
    ]

    return {"data": result}

@frappe.whitelist()
def finish_consignment_transfer(data=None):
    """Finish consignment transfer by submitting the Stock Entry."""

    if isinstance(data, str):
        data = json.loads(data)

    data = data or frappe.form_dict

    pick_list = frappe.db.get_value("Packing List", data.get("packing_list_id"), "pick_list")

    #get the transit stock entry for the packing list
    transit_se = frappe.get_doc(
        "Stock Entry",
        {
            "pick_list": pick_list,
            "add_to_transit": 1,
            "is_consignment": 1,
            "docstatus": 1
        }
    )

    stock_entry = frappe.get_doc(make_stock_in_entry(transit_se.name))
    stock_entry.from_warehouse = transit_se.to_warehouse
    stock_entry.to_warehouse = transit_se.destination_warehouse
    stock_entry.destination_warehouse = None
    stock_entry.add_to_transit = 0
    stock_entry.pick_list = transit_se.pick_list
    stock_entry.material_request = transit_se.material_request

    stock_entry.submit()

    return {
            "end_transit_stock_entry": stock_entry.name,
            "material_request": transit_se.material_request,
            "from_warehouse": transit_se.to_warehouse,
            "to_warehouse": transit_se.destination_warehouse,
        }