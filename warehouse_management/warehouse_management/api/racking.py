import frappe
import json
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
        filters={
            "docstatus": 1,
        },
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
            [
                "status",
                "workflow_state",
                "set_warehouse",
            ],
            as_dict=True,
        )

        if mr.workflow_state != "Completed":
            continue

        if mr.set_warehouse != warehouse:
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
            fields=[
                "box_id",
            ],
            order_by="idx asc",
        )

        # Check boxes pending racking
        pending_boxes = 0

        for packing_box in boxes:
            box = frappe.get_doc("Box", packing_box.box_id)
            box_pending = False

            for item in box.items:
                racked_qty = flt(item.racked_qty)

                if racked_qty < flt(item.qty):
                    box_pending = True
                    break

            if box_pending:
                pending_boxes += 1

        if pending_boxes == 0:
            continue

        result.append(
            {
                "packing_list": packing_list.name,
                "material_request": packing_list.material_request,
                "total_boxes": packing_list.total_boxes,
                "received_boxes": packing_list.received_boxes,
                "pending_boxes": pending_boxes,
            }
        )

    return result


@frappe.whitelist()
def get_racking_packing_list_details(packing_list):
    """
    Return received boxes that are pending racking.
    """

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
        box = frappe.get_doc("Box", packing_box.box_id)
        pending = False

        for item in box.items:
            if flt(item.racked_qty) < flt(item.qty):
                pending = True
                break

        if not pending:
            continue

        result.append(
            {
                "box_id": packing_box.box_id,
                "total_item": packing_box.total_item,
                "is_received": packing_box.is_received,
            }
        )

    return {
        "total_box_count": len(result),
        "items": result,
    }


import frappe


@frappe.whitelist(methods=["GET"])
def get_racking_box_item(box_id=None):
    """Get item details from Box."""

    box_id = box_id or frappe.form_dict.get("box_id")

    if not box_id:
        frappe.throw("Box ID is required.")

    box_name = frappe.db.get_value(
        "Box",
        {"box_id": box_id},
        "name"
    )

    if not box_name:
        box_name = frappe.db.get_value(
            "Box",
            {"name": box_id},
            "name"
        )

    if not box_name:
        frappe.throw(f"Box '{box_id}' does not exist.")

    box = frappe.get_doc("Box", box_name)

    if not frappe.has_permission("Box", "read", doc=box):
        frappe.throw(
            "You do not have permission to view this Box.",
            frappe.PermissionError
        )

    items = []

    for row in box.items:
        item_details = frappe.db.get_value(
            "Item",
            row.item,
            ["item_code", "item_name", "stock_uom"],
            as_dict=True
        )

        if not item_details:
            frappe.throw(
                f"Item '{row.item}' linked to Box '{box_id}' does not exist."
            )

        items.append({
            "item_code": item_details.item_code,
            "item_name": item_details.item_name,
            "qty": row.qty,
            "racked_qty": (
                row.get("racked_qty")
                if row.meta.has_field("racked_qty")
                else None
            ),
            "uom": row.uom or item_details.stock_uom
        })

    return {"items": items}



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

    box_name = data.get("box")
    item_code = data.get("item")
    qty = flt(data.get("qty"))
    rack = data.get("rack")
    bin_name = data.get("bin")
    storage_warehouse = data.get("storage_warehouse")

    box = frappe.get_doc("Box", box_name)

    box_item = None

    for row in box.items:
        if row.item == item_code:
            box_item = row
            break

    # ---------------------------------------------------------
    # Calculate Pending Quantity
    # ---------------------------------------------------------

    racked_qty = flt(box_item.racked_qty)
    box_qty = flt(box_item.qty)
    pending_qty = box_qty - racked_qty

    if pending_qty <= 0:
        frappe.throw(
            _("Item {0} in Box {1} is already completely racked.")
            .format(
                item_code,
                box_name,
            )
        )

    if qty > pending_qty:
        frappe.throw(
            _(
                "Racking quantity {0} cannot exceed "
                "pending quantity {1} for Item {2}."
            ).format(
                qty,
                pending_qty,
                item_code,
            )
        )

    # ---------------------------------------------------------
    # Verify Box is Received
    # ---------------------------------------------------------

    packing_list = frappe.db.get_value("Box", box_name, "packing_list")

    is_received = frappe.db.get_value(
        "Packing List Box",
        {
            "parent": packing_list,
            "parenttype": "Packing List",
            "parentfield": "items",
            "box_id": box_name,
        },
        "is_received",
    )

    if not is_received:
        frappe.throw(
            _("Box {0} has not been received at Bay.")
            .format(box_name)
        )

    # ---------------------------------------------------------
    # Find Bay Warehouse
    # ---------------------------------------------------------

    material_request = frappe.db.get_value("Packing List", packing_list, "material_request")

    destination_warehouse = frappe.db.get_value("Material Request", material_request, "set_warehouse")

    bay_warehouse = frappe.db.get_value(
        "Warehouse",
        {
            "main_warehouse": destination_warehouse,
            "warehouse_type": "Bay",
            "is_sub_warehouse": 1,
        },
        "name",
    )

    # Validate Storage Bin
    bin_doc = frappe.get_doc("Storage Bin", bin_name)

    if bin_doc.assigned_item and bin_doc.assigned_item != item_code:
        frappe.throw(
            _(
                "Storage Bin {0} is already assigned "
                "to Item {1}."
            ).format(
                bin_name,
                bin_doc.assigned_item,
            )
        )

    # Validate Rack
    if hasattr(bin_doc, "rack"):
        if bin_doc.rack and bin_doc.rack != rack:
            frappe.throw(
                _(
                    "Storage Bin {0} belongs to Rack {1}."
                ).format(
                    bin_name,
                    bin_doc.rack,
                )
            )

    # ---------------------------------------------------------
    # Create Stock Entry
    # ---------------------------------------------------------

    stock_entry = frappe.new_doc("Stock Entry")

    stock_entry.stock_entry_type = "Material Transfer"
    stock_entry.from_warehouse = bay_warehouse
    stock_entry.to_warehouse = storage_warehouse
    stock_entry.material_request = material_request

    stock_entry_item = stock_entry.append("items", {})
    stock_entry_item.item_code = item_code
    stock_entry_item.qty = qty
    stock_entry_item.s_warehouse = bay_warehouse
    stock_entry_item.t_warehouse = storage_warehouse
    stock_entry_item.rack = rack
    stock_entry_item.bin = bin_name

    stock_entry.insert()
    stock_entry.submit()

    # Update Racked Quantity
    box_item.racked_qty = racked_qty + qty
    box.save(ignore_permissions=True)

    return {
        "stock_entry": stock_entry.name,
        "box": box_name,
        "item": item_code,
        "qty": qty,
        "racked_qty": box_item.racked_qty,
        "pending_qty": box_qty - box_item.racked_qty,
        "rack": rack,
        "bin": bin_name,
        "storage_warehouse": storage_warehouse,
    }