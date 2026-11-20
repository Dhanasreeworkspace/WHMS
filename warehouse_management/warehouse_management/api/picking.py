import json

import frappe
from frappe import _
from frappe.utils import flt, nowdate

from erpnext.stock.doctype.material_request.material_request import create_pick_list as make_pick_list


@frappe.whitelist()
def get_material_requests(source_warehouse):
    user = frappe.session.user

    material_requests = frappe.get_all(
        "Material Request",
        filters={
            "workflow_state": "Approved",
            "material_request_type": "Material Transfer",
            "set_from_warehouse": source_warehouse,
            "docstatus": 1,
        },
        fields=[
            "name",
            "set_from_warehouse",
            "set_warehouse",
        ],
        order_by="modified desc",
    )

    if not material_requests:
        return {"data": []}

    mr_names = [mr.name for mr in material_requests]

    pick_lists = frappe.get_all(
        "Pick List",
        filters={
            "material_request": ["in", mr_names],
            "docstatus": 0,
        },
        fields=["name", "material_request"],
    )

    pick_list_map = {
        row.material_request: row.name
        for row in pick_lists
    }

    picked_qty = {}

    if pick_lists:
        locations = frappe.get_all(
            "Pick List Item",
            filters={
                "parent": ["in", [row.name for row in pick_lists]],
                "parenttype": "Pick List",
                "parentfield": "locations",
            },
            fields=["material_request_item", "qty"],
        )

        for row in locations:
            picked_qty[row.material_request_item] = (
                picked_qty.get(row.material_request_item, 0)
                + flt(row.qty)
            )

    mr_items = frappe.get_all(
        "Material Request Item",
        filters={"parent": ["in", mr_names]},
        fields=[
            "name",
            "parent",
            "qty",
            "assigned_picker",
            "is_picking_skipped",
        ],
    )

    pending_mrs = set()

    for row in mr_items:
        if row.assigned_picker and row.assigned_picker != user:
            continue

        if row.is_picking_skipped:
            continue

        if flt(picked_qty.get(row.name, 0)) < flt(row.qty):
            pending_mrs.add(row.parent)

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
            if mr.name in pending_mrs
        ]
    }


@frappe.whitelist()
def get_material_request_stock(mr_id, brand=None):
    mr = frappe.get_doc("Material Request", mr_id)

    warehouse = mr.set_from_warehouse
    user = frappe.session.user

    filtered_items = [
        row for row in mr.items
        if (
            not row.assigned_picker
            or row.assigned_picker == user
        )
        and (not brand or row.brand == brand)
    ]

    item_codes = list({row.item_code for row in filtered_items})

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

    draft_pick_list = frappe.db.get_value(
        "Pick List",
        {
            "material_request": mr.name,
            "docstatus": 0,
        },
        "name",
    )

    picked_by_item = {}

    if draft_pick_list:
        locations = frappe.get_all(
            "Pick List Item",
            filters={
                "parent": draft_pick_list,
                "parenttype": "Pick List",
                "parentfield": "locations",
            },
            fields=["material_request_item", "qty"],
        )

        for row in locations:
            picked_by_item[row.material_request_item] = (
                picked_by_item.get(row.material_request_item, 0)
                + flt(row.qty)
            )

    return {
        "mr_id": mr.name,
        "warehouse": warehouse,
        "pick_list": draft_pick_list,
        "items": [
            {
                "material_request_item": row.name,
                "item_code": row.item_code,
                "item_name": row.item_name,
                "brand": row.brand,
                "req_qty": row.qty,
                "wh_stock_bal": stock_by_item.get(row.item_code, 0),
                "picked_qty": picked_by_item.get(row.name, 0),
                "uom": row.uom,
                "is_picking_skipped": row.is_picking_skipped,
            }
            for row in filtered_items
        ],
    }


@frappe.whitelist()
def get_item_storage_bins(warehouse, item_code=None, barcode=None):
    if barcode:
        barcode_item = frappe.db.get_value(
            "Item Barcode",
            {"barcode": barcode},
            "parent",
        )

        if not barcode_item:
            frappe.throw(_("Item not found for the provided Barcode."))

        item_code = barcode_item

    item = frappe.get_doc("Item", item_code)

    # Include the main warehouse and its sub-warehouses.
    warehouses = [warehouse] + frappe.get_all(
        "Warehouse",
        filters={
            "main_warehouse": warehouse,
            "is_sub_warehouse": 1,
            "disabled": 0,
        },
        pluck="name",
    )

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

    bins = []

    if bin_items:
        storage_bins = frappe.get_all(
            "Storage Bin",
            filters={
                "name": ["in", list({row.parent for row in bin_items})],
                "warehouse": ["in", warehouses],
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
        "barcode": barcode or (item.barcodes[0].barcode if item.barcodes else None),
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

    mr_items = {
        row.name: row
        for row in mr.items
    }

    picked_qty = {}

    for row in pick_list.locations:
        picked_qty[row.material_request_item] = (
            picked_qty.get(row.material_request_item, 0)
            + flt(row.qty)
        )

    requested_bins = {}
    current_qty = {}
    skipped_items = {}

    for item in items:
        mr_item_name = item.get("material_request_item")
        mr_item = mr_items.get(mr_item_name)

        if not mr_item:
            frappe.throw(_("Invalid Material Request Item."))

        if item.get("item_code") != mr_item.item_code:
            frappe.throw(_("Item does not match Material Request Item."))

        if (
            mr_item.assigned_picker
            and mr_item.assigned_picker != frappe.session.user
        ):
            frappe.throw(
                _("Item {0} is assigned to another picker.")
                .format(mr_item.item_code)
            )

        is_skipped = item.get("is_picking_skipped")

        if is_skipped is not None:
            if str(is_skipped) not in ("0", "1"):
                frappe.throw(_("Invalid Picking Skipped value."))

            skipped_items[mr_item_name] = int(is_skipped)

        bins = frappe.parse_json(item.get("bins") or [])

        for bin_row in bins:
            bin_name = bin_row.get("bin")
            qty = flt(bin_row.get("qty"))

            if not bin_name or qty <= 0:
                frappe.throw(_("Invalid Storage Bin or picking quantity."))

            bin_key = (bin_name, mr_item_name)

            if bin_key not in requested_bins:
                requested_bins[bin_key] = {
                    "item_code": mr_item.item_code,
                    "qty": 0,
                    "uom": bin_row.get("uom") or mr_item.uom,
                }

            requested_bins[bin_key]["qty"] += qty

            current_qty[mr_item_name] = (
                current_qty.get(mr_item_name, 0) + qty
            )

    for mr_item_name, qty in current_qty.items():
        mr_item = mr_items[mr_item_name]

        total_qty = picked_qty.get(mr_item_name, 0) + qty

        if total_qty > flt(mr_item.qty):
            frappe.throw(
                _(
                    "Picking quantity {0} for Item {1} cannot exceed "
                    "Material Request quantity {2}."
                ).format(
                    total_qty,
                    mr_item.item_code,
                    mr_item.qty,
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

    requested_bin_qty = {}

    for (bin_name, mr_item_name), request in requested_bins.items():
        key = (bin_name, request["item_code"])

        requested_bin_qty[key] = (
            requested_bin_qty.get(key, 0) + request["qty"]
        )

    for (bin_name, item_code), qty in requested_bin_qty.items():
        storage_bin = storage_bin_map.get(bin_name)

        if not storage_bin:
            frappe.throw(
                _("Storage Bin {0} does not exist.").format(bin_name)
            )

        if storage_bin.warehouse != mr.set_from_warehouse:
            frappe.throw(
                _(
                    "Storage Bin {0} is not assigned to source warehouse {1}."
                ).format(
                    bin_name,
                    mr.set_from_warehouse,
                )
            )

        item_row = bin_item_map.get((bin_name, item_code))

        if not item_row:
            frappe.throw(
                _("Item {0} is not available in Storage Bin {1}.")
                .format(item_code, bin_name)
            )

        if qty > flt(item_row.quantity):
            frappe.throw(
                _(
                    "Insufficient quantity of Item {0} in Storage Bin {1}. "
                    "Available: {2}, Requested: {3}"
                ).format(
                    item_code,
                    bin_name,
                    item_row.quantity,
                    qty,
                )
            )

    location_map = {
        row.material_request_item: row
        for row in pick_list.locations
    }

    for mr_item_name, qty in current_qty.items():
        row = location_map.get(mr_item_name)

        if row:
            row.qty += qty
            row.stock_qty = row.qty * flt(row.conversion_factor or 1)
            continue

        mr_item = mr_items[mr_item_name]

        pick_list.append(
            "locations",
            {
                "item_code": mr_item.item_code,
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

    if not pick_list.locations:
        for mr_item_name, is_skipped in skipped_items.items():
            frappe.db.set_value(
                "Material Request Item",
                mr_item_name,
                "is_picking_skipped",
                is_skipped,
                update_modified=False,
            )

        return {
            "pick_list": None,
            "bin_assignments": [],
            "status": "Draft",
        }

    if pick_list.is_new():
        pick_list.insert(ignore_permissions=True)
    else:
        pick_list.save(ignore_permissions=True)

    for mr_item_name, is_skipped in skipped_items.items():
        frappe.db.set_value(
            "Material Request Item",
            mr_item_name,
            "is_picking_skipped",
            is_skipped,
            update_modified=False,
        )

    bin_assignment_names = []

    for (bin_name, mr_item_name), request in requested_bins.items():
        item_code = request["item_code"]
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

    # Update picked bin details in Pick List Item
    update_picked_bins(pick_list.name)

    return {
        "pick_list": pick_list.name,
        "bin_assignments": bin_assignment_names,
        "status": "Draft",
    }


@frappe.whitelist()
def complete_picking(pick_list=None, mr_id=None):
    if pick_list:
        pick_list = frappe.get_doc("Pick List", pick_list)
        mr_id = pick_list.material_request

    mr = frappe.get_doc("Material Request", mr_id)

    if mr.docstatus != 1 or mr.workflow_state != "Approved":
        frappe.throw(_("Material Request is not available for picking."))

    if not pick_list:
        pick_list_name = frappe.db.get_value(
            "Pick List",
            {
                "material_request": mr.name,
                "docstatus": 0,
            },
            "name",
        )

        pick_list = (
            frappe.get_doc("Pick List", pick_list_name)
            if pick_list_name
            else None
        )

    if pick_list and pick_list.docstatus != 0:
        frappe.throw(_("Pick List must be in Draft status."))

    picked_qty = {}

    if pick_list:
        for row in pick_list.locations:
            picked_qty[row.material_request_item] = (
                picked_qty.get(row.material_request_item, 0)
                + flt(row.qty)
            )

    user = frappe.session.user

    my_pending_items = []
    pending_items = []

    for row in mr.items:
        picked = flt(picked_qty.get(row.name, 0))
        required = flt(row.qty)

        if picked >= required or row.is_picking_skipped:
            continue

        pending_items.append(row.item_code)

        if not row.assigned_picker or row.assigned_picker == user:
            my_pending_items.append(row.item_code)

    if my_pending_items:
        frappe.throw(
            _(
                "Please complete picking or mark Picking Skipped "
                "for the following items: {0}"
            ).format(", ".join(my_pending_items))
        )

    if pending_items:
        return {
            "pick_list": pick_list.name if pick_list else None,
            "status": "Waiting",
            "message": "Waiting for other pickers to complete picking.",
        }

    if not pick_list or not pick_list.locations:
        frappe.throw(
            _("No items were picked. An empty Pick List cannot be submitted.")
        )

    pick_list.submit()

    return {
        "pick_list": pick_list.name,
        "status": "Submitted",
    }


def update_picked_bins(pick_list_name):
    """Update picked bin summary in Pick List Item rows."""

    pick_list = frappe.get_doc("Pick List", pick_list_name)

    bin_assignments = frappe.get_all(
        "Bin Assignment",
        filters={
            "pick_list": pick_list_name,
            "assignment_type": "Picking",
        },
        fields=[
            "item",
            "bin",
            "quantity",
        ],
        order_by="creation asc",
    )

    # Group quantities by item and bin
    picked_bins = {}

    for assignment in bin_assignments:
        item_code = assignment.item
        bin_name = assignment.bin

        item_bins = picked_bins.setdefault(item_code, {})

        item_bins[bin_name] = (
            item_bins.get(bin_name, 0)
            + abs(flt(assignment.quantity))
        )

    # Update existing Pick List Item rows
    for row in pick_list.locations:
        bins = picked_bins.get(row.item_code, {})

        row.picked_bins = ", ".join(
            f"{bin_name} ({qty:g})"
            for bin_name, qty in bins.items()
        )

    pick_list.save(ignore_permissions=True)