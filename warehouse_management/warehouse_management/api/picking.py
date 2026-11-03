import json

import frappe
from frappe import _
from frappe.utils import flt, nowdate

from erpnext.stock.doctype.material_request.material_request import create_pick_list as make_pick_list


@frappe.whitelist()
def get_material_requests(source_warehouse):
    material_requests = frappe.get_all(
        "Material Request",
        filters={
            "workflow_state": "Approved",
            "material_request_type": "Material Transfer",
            "set_from_warehouse": source_warehouse,
        },
        fields=["name", "set_from_warehouse", "set_warehouse"],
        order_by="modified desc",
    )

    if not material_requests:
        return {"data": []}

    mr_names = [mr.name for mr in material_requests]

    pick_lists = frappe.get_all(
        "Pick List",
        filters={
            "material_request": ["in", mr_names],
            "docstatus": ["<", 2],
        },
        fields=["name", "material_request", "modified"],
        order_by="modified desc",
    )

    pick_list_map = {}

    for row in pick_lists:
        if row.material_request not in pick_list_map:
            pick_list_map[row.material_request] = row.name

    return {
        "data": [
            {
                "mr_id": mr.name,
                "source_warehouse": mr.set_from_warehouse,
                "target_warehouse": mr.set_warehouse,
                "pick_list": pick_list_map.get(mr.name),
                "status": (
                    "In Progress"
                    if mr.name in pick_list_map
                    else "To Start"
                ),
            }
            for mr in material_requests
        ]
    }


@frappe.whitelist()
def get_material_request_stock(mr_id, brand=None):
    mr = frappe.get_doc("Material Request", mr_id)

    warehouse = mr.set_from_warehouse

    # Filter MR items by brand
    filtered_items = [
        row for row in mr.items
        if not brand or row.brand == brand
    ]

    item_codes = [row.item_code for row in filtered_items]

    stock_by_item = {}

    if warehouse and item_codes:
        bins = frappe.get_all(
            "Bin",
            filters={
                "warehouse": warehouse,
                "item_code": ["in", item_codes],
            },
            fields=["item_code", "actual_qty"],
        )

        stock_by_item = {
            row.item_code: row.actual_qty or 0
            for row in bins
        }

    pick_lists = frappe.get_all(
        "Pick List",
        filters={
            "material_request": mr.name,
            "docstatus": ["<", 2],
        },
        fields=["name", "docstatus", "modified"],
        order_by="modified desc",
    )

    pick_list = pick_lists[0] if pick_lists else None
    picked_by_item = {}

    if pick_list and item_codes:
        locations = frappe.get_all(
            "Pick List Item",
            filters={
                "parent": pick_list.name,
                "item_code": ["in", item_codes],
            },
            fields=["item_code", "qty"],
        )

        for row in locations:
            picked_by_item[row.item_code] = (
                picked_by_item.get(row.item_code, 0) + flt(row.qty)
            )

    return {
        "mr_id": mr.name,
        "warehouse": warehouse,
        "pick_list": pick_list.name if pick_list else None,
        "items": [
            {
                "item_code": row.item_code,
                "item_name": row.item_name,
                "brand": row.brand,
                "req_qty": row.qty,
                "wh_stock_bal": stock_by_item.get(row.item_code, 0),
                "picked_qty": picked_by_item.get(row.item_code, 0),
                "uom": row.uom,
            }
            for row in filtered_items
        ],
    }


@frappe.whitelist()
def get_item_storage_bins(item_code, warehouse):
    item = frappe.get_doc("Item", item_code)

    bin_items = frappe.get_all(
        "Storage Bin Item",
        filters={
            "item": item_code,
            "parenttype": "Storage Bin",
            "parentfield": "items",
            "quantity": [">", 0],
        },
        fields=["parent", "quantity", "uom"],
        order_by="parent asc",
    )

    if not bin_items:
        bins = []
    else:
        storage_bins = frappe.get_all(
            "Storage Bin",
            filters={
                "name": ["in", list({row.parent for row in bin_items})],
                "warehouse": warehouse,
            },
            fields=["name", "rack"],
        )

        storage_bin_map = {row.name: row for row in storage_bins}

        bins = [
            {
                "bin": row.parent,
                "rack": storage_bin_map[row.parent].rack,
                "qty": row.quantity,
                "uom": row.uom,
            }
            for row in bin_items
            if row.parent in storage_bin_map
        ]

    return {
        "item_code": item_code,
        "item_name": item.item_name,
        "barcode": item.barcodes[0].barcode if item.barcodes else None,
        "warehouse": warehouse,
        "storage_bins": bins,
    }


@frappe.whitelist()
def create_pick_list_from_bins(data=None):
    if isinstance(data, str):
        data = json.loads(data)

    data = data or frappe.form_dict

    mr_id = data.get("mr_id")
    items = data.get("items") or []

    mr = frappe.get_doc("Material Request", mr_id)

    pick_list_name = frappe.db.exists(
        "Pick List",
        {
            "material_request": mr.name,
            "docstatus": 0,
        },
    )

    if pick_list_name:
        pick_list = frappe.get_doc("Pick List", pick_list_name)
    else:
        pick_list = make_pick_list(mr.name)
        pick_list.pick_manually = 1
        pick_list.source_warehouse = mr.set_from_warehouse
        pick_list.destination_warehouse = mr.set_warehouse
        pick_list.locations = []

    mr_qty = {}
    mr_items = {}

    for row in mr.items:
        mr_qty[row.item_code] = (
            mr_qty.get(row.item_code, 0) + flt(row.qty)
        )
        mr_items[row.item_code] = row

    picked_qty = {}

    for row in pick_list.locations:
        picked_qty[row.item_code] = (
            picked_qty.get(row.item_code, 0) + flt(row.qty)
        )

    requested_bins = {}
    current_qty = {}

    for item in items:
        item_code = item.get("item_code")
        bins = item.get("bins") or []

        for bin_row in bins:
            bin_name = bin_row.get("bin")
            qty = flt(bin_row.get("qty"))

            bin_key = (bin_name, item_code)

            if bin_key not in requested_bins:
                requested_bins[bin_key] = {
                    "item_code": item_code,
                    "qty": 0,
                    "uom": bin_row.get("uom") or mr_items[item_code].uom,
                }

            requested_bins[bin_key]["qty"] += qty

            current_qty[item_code] = (
                current_qty.get(item_code, 0) + qty
            )

    for item_code, qty in current_qty.items():
        total_qty = picked_qty.get(item_code, 0) + qty

        if total_qty > mr_qty[item_code]:
            frappe.throw(
                _(
                    "Picking quantity {0} for Item {1} cannot be greater "
                    "than Material Request quantity {2}."
                ).format(
                    total_qty,
                    item_code,
                    mr_qty[item_code],
                )
            )

    # Get unique Storage Bin names from requested bin/item pairs.
    bin_names = list({
        bin_name
        for bin_name, item_code in requested_bins
    })

    # Fetch Storage Bin parent documents.
    storage_bins = frappe.get_all(
        "Storage Bin",
        filters={"name": ["in", bin_names]},
        fields=["name", "rack", "warehouse"],
    )

    storage_bin_map = {
        row.name: frappe.get_doc("Storage Bin", row.name)
        for row in storage_bins
    }

    # Fetch child rows using parent (Storage Bin name).
    bin_items = frappe.get_all(
        "Storage Bin Item",
        filters={
            "parent": ["in", bin_names],
            "parenttype": "Storage Bin",
            "parentfield": "items",
        },
        fields=["parent", "item", "quantity", "uom"],
    )

    # Map using Storage Bin + Item.
    bin_item_map = {
        (row.parent, row.item): row
        for row in bin_items
    }

    # Validate requested quantities against the matching child row.
    for (bin_name, item_code), request in requested_bins.items():

        storage_bin = storage_bin_map.get(bin_name)

        if not storage_bin:
            frappe.throw(
                _("Storage Bin {0} does not exist.").format(bin_name)
            )

        item_row = bin_item_map.get((bin_name, item_code))

        if not item_row:
            frappe.throw(
                _("Item {0} is not available in Storage Bin {1}.")
                .format(item_code, bin_name)
            )

        if request["qty"] > flt(item_row.quantity):
            frappe.throw(
                _(
                    "Insufficient quantity of Item {0} in Storage Bin {1}. "
                    "Available: {2}, Requested: {3}"
                ).format(
                    item_code,
                    bin_name,
                    item_row.quantity,
                    request["qty"]
                )
            )

    location_map = {row.item_code: row for row in pick_list.locations}

    for item_code, qty in current_qty.items():
        row = location_map.get(item_code)

        if row:
            row.qty += qty
            row.stock_qty = row.qty * flt(row.conversion_factor or 1)
            continue

        mr_item = mr_items[item_code]

        pick_list.append(
            "locations",
            {
                "item_code": item_code,
                "item_name": mr_item.item_name,
                "description": mr_item.description,
                "qty": qty,
                "stock_qty": qty * flt(mr_item.conversion_factor or 1),
                "uom": mr_item.uom,
                "stock_uom": mr_item.stock_uom,
                "conversion_factor": mr_item.conversion_factor or 1,
                "warehouse": mr.set_from_warehouse,
                "material_request": mr.name,
                "material_request_item": mr_item.name,
            },
        )

    pick_list.pick_manually = 1
    pick_list.source_warehouse = mr.set_from_warehouse
    pick_list.destination_warehouse = mr.set_warehouse

    if pick_list.is_new():
        pick_list.insert(ignore_permissions=True)
    else:
        pick_list.save(ignore_permissions=True)

    bin_assignment_names = []

    for (bin_name, item_code), request in requested_bins.items():

        storage_bin = storage_bin_map[bin_name]

        bin_assignment = frappe.get_doc({
            "doctype": "Bin Assignment",
            "item": item_code,
            "uom": request["uom"],
            "rack": storage_bin.rack,
            "bin": bin_name,
            "quantity": -request["qty"],
            "doa": nowdate(),
            "assignment_type": "Picking",
            "material_request": mr.name,
            "pick_list": pick_list.name,
        })

        bin_assignment.insert(ignore_permissions=True)
        bin_assignment_names.append(bin_assignment.name)

    return {
        "pick_list": pick_list.name,
        "bin_assignments": bin_assignment_names,
        "status": "Draft",
    }


@frappe.whitelist()
def complete_picking(pick_list):
    pick_list = frappe.get_doc("Pick List", pick_list)
    mr = frappe.get_doc("Material Request", pick_list.material_request)

    required = {}
    picked = {}

    for row in mr.items:
        required[row.item_code] = (
            required.get(row.item_code, 0) + flt(row.qty)
        )

    for row in pick_list.locations:
        picked[row.item_code] = (
            picked.get(row.item_code, 0) + flt(row.qty)
        )

    for item_code, required_qty in required.items():
        picked_qty = picked.get(item_code, 0)

        if picked_qty != required_qty:
            frappe.throw(
                _(
                    "Picking is incomplete for Item {0}. "
                    "Required: {1}, Picked: {2}."
                ).format(item_code, required_qty, picked_qty)
            )

    pick_list.submit()

    return {
        "pick_list": pick_list.name,
        "status": "Submitted",
    }