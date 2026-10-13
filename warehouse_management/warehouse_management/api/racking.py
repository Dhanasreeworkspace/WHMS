import json

import frappe
from frappe import _
from frappe.utils import flt


@frappe.whitelist()
def get_racking_packing_lists(warehouse):
    """
    Return Packing Lists for the selected warehouse whose
    Material Request workflow state is Completed and which
    still have boxes pending racking.
    """

    packing_lists = frappe.get_all(
        "Packing List",
        filters={"docstatus": 1},
        fields=[
            "name",
            "material_request",
            "total_boxes",
            "received_boxes",
        ],
        order_by="creation desc",
    )

    result = []

    for packing_list in packing_lists:
        mr = frappe.db.get_value(
            "Material Request",
            packing_list.material_request,
            ["workflow_state", "set_warehouse"],
            as_dict=True,
        )

        if mr.workflow_state != "Completed" or mr.set_warehouse != warehouse:
            continue

        # Get Bay warehouse
        bay_warehouse = frappe.db.get_value(
            "Warehouse",
            {
                "main_warehouse": warehouse,
                "warehouse_type": "Bay",
                "is_sub_warehouse": 1,
            },
            "name",
        )

        # Get racking Stock Entries
        stock_entries = frappe.get_all(
            "Stock Entry",
            filters={
                "material_request": packing_list.material_request,
                "stock_entry_type": "Material Transfer",
                "from_warehouse": bay_warehouse,
                "docstatus": ["!=", 2],
            },
            fields=["name", "docstatus"],
        )

        # Determine racking status
        racking_status = "To Start"

        for entry in stock_entries:
            if entry.docstatus == 1:
                racking_status = "Completed"
                break
            elif entry.docstatus == 0:
                racking_status = "In Progress"

        if racking_status == "Completed":
            continue

        # Get received boxes
        boxes = frappe.get_all(
            "Packing List Box",
            filters={
                "parent": packing_list.name,
                "parenttype": "Packing List",
                "parentfield": "items",
                "is_received": 1,
            },
            fields=["box_id"],
            order_by="idx asc",
        )

        if not boxes:
            continue

        result.append({
            "packing_list": packing_list.name,
            "material_request": packing_list.material_request,
            "total_boxes": packing_list.total_boxes,
            "racking_status": racking_status,
        })

    return result


@frappe.whitelist()
def get_racking_packing_list_details(packing_list):
    """Return received boxes based on racking Stock Entry status."""

    material_request = frappe.db.get_value(
        "Packing List",
        packing_list,
        "material_request",
    )

    main_warehouse = frappe.db.get_value(
        "Material Request",
        material_request,
        "set_warehouse",
    )

    bay_warehouse = frappe.db.get_value(
        "Warehouse",
        {
            "main_warehouse": main_warehouse,
            "warehouse_type": "Bay",
            "is_sub_warehouse": 1,
        },
        "name",
    )

    # Check whether racking Stock Entry is submitted
    submitted_stock_entry = frappe.db.exists(
        "Stock Entry",
        {
            "material_request": material_request,
            "stock_entry_type": "Material Transfer",
            "from_warehouse": bay_warehouse,
            "docstatus": 1,
        },
    )

    if submitted_stock_entry:
        return {
            "total_box_count": 0,
            "items": [],
        }

    # Get received boxes
    boxes = frappe.get_all(
        "Packing List Box",
        filters={
            "parent": packing_list,
            "parenttype": "Packing List",
            "parentfield": "items",
            "is_received": 1,
        },
        fields=[
            "box_id",
            "total_item",
            "is_received",
        ],
        order_by="idx asc",
    )

    result = []

    for packing_box in boxes:
        result.append({
            "box_id": packing_box.box_id,
            "total_item": packing_box.total_item,
            "is_received": packing_box.is_received,
        })

    return {
        "total_box_count": len(result),
        "items": result,
    }

@frappe.whitelist(methods=["GET"])
def get_racking_box_item(box_id, item_id=None, barcode=None):
    """Get item details from Box."""

    box_name = frappe.db.get_value(
        "Box",
        {"box_id": box_id},
        "name",
    )

    box = frappe.get_doc("Box", box_name)

    stock_entry = frappe.db.get_value(
        "Stock Entry",
        {
            "material_request": frappe.db.get_value(
                "Packing List",
                {
                    "name": frappe.db.get_value(
                        "Packing List Box",
                        {"box_id": box_id},
                        "parent",
                    )
                },
                "material_request",
            ),
            "stock_entry_type": "Material Transfer",
            "docstatus": 0,
        },
        "name",
    )

    items = []

    for row in box.items:
        item = frappe.get_doc("Item", row.item)

        if item_id and row.item != item_id:
            continue

        if barcode and not any(
            b.barcode == barcode for b in item.barcodes
        ):
            continue

        total_qty = flt(row.qty)
        racked_qty = flt(row.racked_qty)

        items.append({
            "item_code": item.item_code,
            "item_name": item.item_name,
            "barcode": item.barcodes[0].barcode if item.barcodes else None,
            "qty": total_qty,
            "racked_qty": racked_qty,
            "remaining_qty": total_qty - racked_qty,
            "uom": row.uom or item.stock_uom,
        })

    return {
        "draft_stock_entry": stock_entry or None,
        "items": items,
    }


@frappe.whitelist()
def move_item_to_storage(data=None):
    """
    Move an item from Bay warehouse to Storage warehouse.

    Creates a Material Transfer Stock Entry with Rack and Bin,
    then updates the Box Item racked quantity and Storage Bin.
    """

    if isinstance(data, str):
        data = json.loads(data)

    data = data or frappe.form_dict

    packing_list = data.get("packing_list")
    box_name = data.get("box")
    item_code = data.get("item")
    storage_warehouse = data.get("warehouse")
    allocations = data.get("allocations")

    total_qty = sum(flt(row.get("qty")) for row in allocations)

    # Get Material Request and warehouses
    material_request = frappe.db.get_value(
        "Packing List", packing_list, "material_request"
    )

    main_warehouse = frappe.db.get_value(
        "Material Request", material_request, "set_warehouse"
    )

    bay_warehouse = frappe.db.get_value(
        "Warehouse",
        {
            "main_warehouse": main_warehouse,
            "warehouse_type": "Bay",
            "is_sub_warehouse": 1,
        },
        "name",
    )

    # Get Box and item
    box = frappe.get_doc("Box", box_name)

    box_item = next(
        (row for row in box.items if row.item == item_code),
        None,
    )

    # Check whether Box has been received
    is_received = frappe.db.exists(
        "Packing List Box",
        {
            "parent": packing_list,
            "parenttype": "Packing List",
            "parentfield": "items",
            "box_id": box_name,
            "is_received": 1,
        },
    )

    if not is_received:
        frappe.throw(
            _("Box {0} has not been received at Bay.").format(box_name)
        )

    # Calculate remaining quantity
    total_box_qty = flt(box_item.qty)
    already_racked_qty = flt(box_item.racked_qty)
    remaining_qty = total_box_qty - already_racked_qty

    if total_qty <= 0 or total_qty > remaining_qty:
        frappe.throw(
            _(
                "Cannot rack quantity {0}. Remaining quantity for "
                "Item {1} in Box {2} is {3}."
            ).format(total_qty, item_code, box_name, max(remaining_qty, 0))
        )

    # Validate all Rack and Bin allocations
    for allocation in allocations:
        qty = flt(allocation.get("qty"))
        rack = allocation.get("rack")
        bin_name = allocation.get("bin")

        bin_doc = frappe.get_doc("Storage Bin", bin_name)

        if bin_doc.assigned_item and bin_doc.assigned_item != item_code:
            frappe.throw(
                _("Storage Bin {0} is assigned to Item {1}.").format(
                    bin_name, bin_doc.assigned_item
                )
            )

        if bin_doc.rack and bin_doc.rack != rack:
            frappe.throw(
                _("Storage Bin {0} belongs to Rack {1}.").format(
                    bin_name, bin_doc.rack
                )
            )

    # Get or create draft Stock Entry
    stock_entry_name = frappe.db.get_value(
        "Stock Entry",
        {
            "material_request": material_request,
            "stock_entry_type": "Material Transfer",
            "from_warehouse": bay_warehouse,
            "to_warehouse": storage_warehouse,
            "docstatus": 0,
        },
        "name",
    )

    if stock_entry_name:
        stock_entry = frappe.get_doc("Stock Entry", stock_entry_name)
    else:
        stock_entry = frappe.new_doc("Stock Entry")
        stock_entry.stock_entry_type = "Material Transfer"
        stock_entry.material_request = material_request
        stock_entry.from_warehouse = bay_warehouse
        stock_entry.to_warehouse = storage_warehouse

    # Add each Rack and Bin allocation
    for allocation in allocations:
        qty = flt(allocation.get("qty"))
        rack = allocation.get("rack")
        bin_name = allocation.get("bin")

        existing_item = next(
            (
                row for row in stock_entry.items
                if row.item_code == item_code
                and row.s_warehouse == bay_warehouse
                and row.t_warehouse == storage_warehouse
                and row.rack == rack
                and row.bin == bin_name
            ),
            None,
        )

        if existing_item:
            existing_item.qty = flt(existing_item.qty) + qty
        else:
            stock_entry.append(
                "items",
                {
                    "item_code": item_code,
                    "qty": qty,
                    "s_warehouse": bay_warehouse,
                    "t_warehouse": storage_warehouse,
                    "rack": rack,
                    "bin": bin_name,
                },
            )

    if stock_entry.is_new():
        stock_entry.insert()
    else:
        stock_entry.save()

    box_item.racked_qty = already_racked_qty + total_qty
    box.save(ignore_permissions=True)

    return {
        "stock_entry": stock_entry.name,
        "status": "Draft",
        "from_warehouse": bay_warehouse,
        "to_warehouse": storage_warehouse,
        "total_qty": total_box_qty,
        "racked_qty": box_item.racked_qty,
        "remaining_qty": total_box_qty - flt(box_item.racked_qty),
        "message": _("Item added to the racking Stock Entry."),
    }


@frappe.whitelist()
def complete_racking(data=None):
    """Validate and submit the draft racking Stock Entry."""

    if isinstance(data, str):
        data = json.loads(data)

    data = data or frappe.form_dict

    stock_entry = frappe.get_doc("Stock Entry", data.get("stock_entry"))

    if stock_entry.docstatus == 1:
        return {
            "stock_entry": stock_entry.name,
            "status": "Submitted",
            "message": _("Racking already completed."),
        }

    bay_warehouse = frappe.db.exists(
        "Warehouse",
        {
            "name": stock_entry.from_warehouse,
            "warehouse_type": "Bay",
            "is_sub_warehouse": 1,
        },
    )

    if not bay_warehouse:
        frappe.throw(_("Source warehouse must be a Bay warehouse."))

    if not stock_entry.items:
        frappe.throw(_("No items found in the Stock Entry."))

    material_request = stock_entry.material_request

    packing_lists = frappe.get_all(
        "Packing List",
        filters={"material_request": material_request},
        pluck="name",
    )

    for packing_list in packing_lists:
        boxes = frappe.get_all(
            "Packing List Box",
            filters={"parent": packing_list, "is_received": 1},
            pluck="box_id",
        )

        for box_id in boxes:
            box_name = frappe.db.get_value(
                "Box",
                {"box_id": box_id},
                "name",
            )

            if not box_name:
                continue

            box = frappe.get_doc("Box", box_name)

            for row in box.items:
                if flt(row.racked_qty) < flt(row.qty):
                    frappe.throw(
                        _("Cannot complete racking. Item {0} in Box {1} is not fully racked. Required: {2}, Racked: {3}.").format(
                            row.item,
                            box_id,
                            row.qty,
                            row.racked_qty,
                        )
                    )

    stock_entry.submit()

    return {
        "stock_entry": stock_entry.name,
        "status": "Submitted",
        "message": _("Racking completed successfully."),
    }