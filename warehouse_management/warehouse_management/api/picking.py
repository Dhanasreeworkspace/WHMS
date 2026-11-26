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
            "is_consignment",
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
            "docstatus": ["<", 2],
        },
        fields=["name", "material_request", "docstatus"],
    )

    draft_pick_list_map = {}
    submitted_mrs = set()

    for row in pick_lists:
        if row.docstatus == 1:
            submitted_mrs.add(row.material_request)
        else:
            draft_pick_list_map[row.material_request] = row.name

    mr_items = frappe.get_all(
        "Material Request Item",
        filters={"parent": ["in", mr_names]},
        fields=["parent", "assigned_picker"],
    )

    visible_mrs = {
        row.parent
        for row in mr_items
        if not row.assigned_picker or row.assigned_picker == user
    }

    return {
        "data": [
            {
                "mr_id": mr.name,
                "source_warehouse": mr.set_from_warehouse,
                "target_warehouse": mr.set_warehouse,
                "is_consignment": mr.is_consignment,
                "pick_list": draft_pick_list_map.get(mr.name),
                "status": (
                    "In Progress"
                    if mr.name in draft_pick_list_map
                    else "To Start"
                ),
            }
            for mr in material_requests
            if mr.name in visible_mrs
            and mr.name not in submitted_mrs
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
        "is_consignment": mr.is_consignment,
        "warehouse": warehouse,
        "pick_list": draft_pick_list,
        "items": [
            {
                "item_code": row.item_code,
                "item_name": row.item_name,
                "brand": row.brand,
                "req_qty": row.qty,
                "wh_stock_bal": stock_by_item.get(row.item_code, 0),
                "picked_qty": picked_by_item.get(row.name, 0),
                "uom": row.uom,
                "skip_validation": row.skip_validation,
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
        pick_list.locations = []

    pick_list.is_consignment = mr.is_consignment
    pick_list.save(ignore_permissions=True)

    mr_items = {
        row.name: row
        for row in mr.items
    }

    mr_items_by_code = {
        row.item_code: row
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
        mr_item = mr_items_by_code.get(item.get("item_code"))

        if not mr_item:
            frappe.throw(
                _("Item {0} not found in Material Request.")
                .format(item.get("item_code"))
            )

        mr_item_name = mr_item.name

        if (
            mr_item.assigned_picker
            and mr_item.assigned_picker != frappe.session.user
        ):
            frappe.throw(
                _("Item {0} is assigned to another picker.")
                .format(mr_item.item_code)
            )

        is_skipped = item.get("skip_validation")

        if is_skipped is not None:
            skipped_items[mr_item_name] = int(is_skipped)

        bins = frappe.parse_json(item.get("bins") or [])

        for bin_row in bins:
            bin_name = bin_row.get("bin")
            qty = flt(bin_row.get("qty"))

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
    bin_names = list({bin_name for bin_name, _ in requested_bins})

    # Fetch Storage Bin parent documents.
    storage_bin_map = {}
    bin_item_map = {}

    if bin_names:
        storage_bins = frappe.get_all(
            "Storage Bin",
            filters={"name": ["in", bin_names]},
            fields=["name", "rack", "warehouse"],
        )

        storage_bin_map = {row.name: row for row in storage_bins}

        bin_items = frappe.get_all(
            "Storage Bin Item",
            filters={
                "parent": ["in", bin_names],
                "parenttype": "Storage Bin",
                "parentfield": "items",
            },
            fields=["parent", "item", "quantity"],
        )

        bin_item_map = {
            (row.parent, row.item): row
            for row in bin_items
        }

    for (bin_name, mr_item_name), request in requested_bins.items():
        item_code = request["item_code"]
        qty = request["qty"]

        storage_bin = storage_bin_map.get(bin_name)
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

    if pick_list.locations:
        if pick_list.is_new():
            pick_list.insert(ignore_permissions=True)
        else:
            pick_list.save(ignore_permissions=True)

    # Update skipped status in Material Request Items
    for mr_item_name, is_skipped in skipped_items.items():
        frappe.db.set_value(
            "Material Request Item",
            mr_item_name,
            "skip_validation",
            is_skipped,
            update_modified=False,
        )

    if not pick_list.locations:
        return {
            "pick_list": None,
            "bin_assignments": [],
            "status": "Draft",
        }

    bin_assignment_names = []

    for (bin_name, mr_item_name), request in requested_bins.items():
        storage_bin = storage_bin_map[bin_name]

        bin_assignment = frappe.get_doc({
            "doctype": "Bin Assignment",
            "item": request["item_code"],
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
    if bin_assignment_names:
        update_picked_bins(pick_list.name)

    return {
        "pick_list": pick_list.name,
        "bin_assignments": bin_assignment_names,
        "status": "Draft",
    }


@frappe.whitelist(methods=["POST"])
def complete_picking(pick_list):
    pick_list = frappe.get_doc("Pick List", pick_list)

    if pick_list.docstatus != 0:
        frappe.throw(_("Pick List must be in Draft status."))

    mr = frappe.get_doc("Material Request", pick_list.material_request)

    if not pick_list.locations:
        frappe.throw(_("No items found in Pick List."))

    picked_qty = {}

    for row in pick_list.locations:
        picked_qty[row.material_request_item] = (
            picked_qty.get(row.material_request_item, 0)
            + flt(row.qty)
        )

    my_pending_items = []
    has_pending_items = False

    for row in mr.items:
        picked = flt(picked_qty.get(row.name, 0))

        if picked >= flt(row.qty) or row.skip_validation:
            continue

        has_pending_items = True

        if not row.assigned_picker or row.assigned_picker == frappe.session.user:
            my_pending_items.append(row.item_code)

    if my_pending_items:
        frappe.throw(
            _(
                "Please complete picking or mark Picking Skipped "
                "for the following items: {0}"
            ).format(", ".join(my_pending_items))
        )

    if has_pending_items:
        return {
            "pick_list": pick_list.name,
            "status": "Waiting",
            "message": "Waiting for other pickers to complete picking.",
        }

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
        ]
    )

    # Group quantities by item and bin
    picked_bins = {}

    for assignment in bin_assignments:
        item_bins = picked_bins.setdefault(assignment.item, {})

        item_bins[assignment.bin] = (
            item_bins.get(assignment.bin, 0)
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