import frappe
from frappe import _
from frappe.utils import flt


@frappe.whitelist()
def get_verification_packing_lists(warehouse):
    """Return Packing Lists pending verification with Box progress."""

    packing_lists = frappe.get_all(
        "Packing List",
        filters={
            "docstatus": 1,
            "destination_warehouse": warehouse,
            "received_boxes": [">", 0],
            "stock_status": ["!=", "Verified"],
        },
        fields=[
            "name",
            "material_request",
            "total_boxes",
            "received_boxes",
            "verified_boxes",
        ],
        order_by="creation desc",
    )

    if not packing_lists:
        return []

    quality_checks = frappe.get_all(
        "Stock Quality Check",
        filters={
            "packing_list": ["in", [row.name for row in packing_lists]],
            "docstatus": ["<", 2],
        },
        fields=["name", "packing_list", "docstatus"],
    )

    quality_map = {
        row.packing_list: row
        for row in quality_checks
    }

    result = []

    for row in packing_lists:
        quality_check = quality_map.get(row.name)

        if quality_check and quality_check.docstatus == 1:
            continue

        result.append({
            "packing_list": row.name,
            "material_request": row.material_request,
            "total_packed_boxes": row.total_boxes,
            "total_received_boxes": row.received_boxes,
            "total_verified_boxes": row.verified_boxes,
            "verification_status": (
                "In Progress" if quality_check else "To Start"
            ),
        })

    return result


@frappe.whitelist()
def get_verification_packing_list_details(packing_list):
    """Return received Boxes with verification progress."""

    boxes = frappe.get_all(
        "Packing List Box",
        filters={
            "parent": packing_list,
            "parenttype": "Packing List",
            "parentfield": "items",
            "is_received": 1,
        },
        fields=["box_id", "total_item", "is_verified"],
        order_by="idx asc",
    )

    box_ids = [row.box_id for row in boxes]

    verified_map = dict(
        frappe.get_all(
            "Box",
            filters={"name": ["in", box_ids]},
            fields=["name", "verified_items"],
            as_list=True,
        )
    ) if box_ids else {}

    quality_check_name = frappe.db.get_value(
        "Stock Quality Check",
        {
            "packing_list": packing_list,
            "docstatus": ["<", 2],
        },
        "name",
    )

    qc_map = {}

    if quality_check_name and box_ids:
        quality_items = frappe.get_all(
            "Stock Quality Check Item",
            filters={
                "parent": quality_check_name,
                "parenttype": "Stock Quality Check",
                "parentfield": "items",
                "box": ["in", box_ids],
            },
            fields=["box", "qc_passed_qty", "flagged_qty"],
        )

        for row in quality_items:
            if row.box not in qc_map:
                qc_map[row.box] = {
                    "qc_passed_items": 0,
                    "flagged_items": 0,
                }

            qc_map[row.box]["qc_passed_items"] += row.qc_passed_qty or 0
            qc_map[row.box]["flagged_items"] += row.flagged_qty or 0

    return {
        "packing_list": packing_list,
        "stock_quality_check": quality_check_name,
        "boxes": [
            {
                "box_id": row.box_id,
                "total_received_items": row.total_item or 0,
                "total_verified_items": verified_map.get(row.box_id, 0) or 0,
                "qc_passed_items": qc_map.get(
                    row.box_id, {}
                ).get("qc_passed_items", 0),
                "flagged_items": qc_map.get(
                    row.box_id, {}
                ).get("flagged_items", 0),
                "is_verified": row.is_verified,
            }
            for row in boxes
        ],
    }


@frappe.whitelist(methods=["GET"])
def get_verification_box_items(packing_list, box_id, item_id=None, barcode=None):
    """Return Box items with saved verification quantities."""

    box = frappe.get_doc("Box", box_id)

    quality_check_name = frappe.db.get_value(
        "Stock Quality Check",
        {
            "packing_list": packing_list,
            "docstatus": ["<", 2],
        },
        "name",
    )

    quality_items = {}

    if quality_check_name:
        quality_check = frappe.get_doc(
            "Stock Quality Check", quality_check_name
        )

        quality_items = {
            row.item: row
            for row in quality_check.items
            if row.box == box_id
        }

    box_items = [
        row for row in box.items
        if not item_id or row.item == item_id
    ]

    if barcode:
        barcode_item = frappe.db.get_value(
            "Item Barcode",
            {"barcode": barcode},
            "parent",
        )

        box_items = [
            row for row in box_items
            if row.item == barcode_item
        ]

    item_codes = list({row.item for row in box_items})

    item_names = dict(
        frappe.get_all(
            "Item",
            filters={"name": ["in", item_codes]},
            fields=["name", "item_name"],
            as_list=True,
        )
    ) if item_codes else {}

    barcodes = frappe.get_all(
        "Item Barcode",
        filters={"parent": ["in", item_codes]},
        fields=["parent", "barcode"],
        order_by="idx asc",
    ) if item_codes else []

    barcode_map = {}

    for row in barcodes:
        barcode_map.setdefault(row.parent, row.barcode)

    items = []

    for row in box_items:
        quality_item = quality_items.get(row.item)

        verified_qty = quality_item.verified_qty if quality_item else 0
        qc_passed_qty = quality_item.qc_passed_qty if quality_item else 0
        flagged_qty = quality_item.flagged_qty if quality_item else 0

        items.append({
            "item_code": row.item,
            "item_name": item_names.get(row.item),
            "barcode": barcode_map.get(row.item),
            "total_received_qty": row.qty,
            "total_verified_qty": verified_qty,
            "qc_passed_qty": qc_passed_qty,
            "flagged_qty": flagged_qty,
            "uom": row.uom,
        })

    return {
        "stock_quality_check": quality_check_name,
        "packing_list": packing_list,
        "box": box_id,
        "items": items,
    }


@frappe.whitelist(methods=["POST"])
def create_box_verification(data=None):
    """Create or update Box Item verification for each scan."""

    data = frappe.parse_json(data) if data else frappe.form_dict

    packing_list = data.get("packing_list")
    box_id = data.get("box")
    item_code = data.get("item")

    qc_passed_qty = flt(data.get("qc_passed_qty"))
    flagged_qty = flt(data.get("flagged_qty"))

    packing_doc = frappe.get_doc("Packing List", packing_list)
    box = frappe.get_doc("Box", box_id)

    box_items = {row.item: row for row in box.items}
    box_item = box_items.get(item_code)

    expected_qty = box_item.qty

    quality_check_name = frappe.db.get_value(
        "Stock Quality Check",
        {"packing_list": packing_list},
        "name",
    )

    if quality_check_name:
        quality_check = frappe.get_doc(
            "Stock Quality Check", quality_check_name
        )

        if quality_check.docstatus != 0:
            frappe.throw(
                _("Packing List verification is already completed.")
            )

    else:
        bay_warehouse = frappe.db.get_value(
            "Warehouse",
            {
                "main_warehouse": packing_doc.destination_warehouse,
                "warehouse_type": "Bay",
                "disabled": 0,
            },
            "name",
        )

        if not bay_warehouse:
            frappe.throw(_("Bay warehouse not found."))

        quality_check = frappe.new_doc("Stock Quality Check")
        quality_check.packing_list = packing_list
        quality_check.material_request = packing_doc.material_request
        quality_check.warehouse = bay_warehouse

    # Find existing verification row for this Box Item.
    quality_item = next(
        (
            row for row in quality_check.items
            if row.box == box_id and row.item == item_code
        ),
        None,
    )

    current_qc_passed_qty = quality_item.qc_passed_qty if quality_item else 0
    current_flagged_qty = quality_item.flagged_qty if quality_item else 0

    # Accumulate quantities from each scan.
    new_qc_passed_qty = current_qc_passed_qty + qc_passed_qty
    new_flagged_qty = current_flagged_qty + flagged_qty
    new_verified_qty = new_qc_passed_qty + new_flagged_qty

    if new_verified_qty > expected_qty:
        frappe.throw(
            _("Verification quantity exceeds expected quantity for Item {0}.").format(
                item_code
            )
        )

    if quality_item:
        quality_item.qc_passed_qty = new_qc_passed_qty
        quality_item.flagged_qty = new_flagged_qty
        quality_item.verified_qty = new_verified_qty
    else:
        quality_check.append("items", {
            "box": box_id,
            "item": item_code,
            "verified_qty": new_verified_qty,
            "qc_passed_qty": new_qc_passed_qty,
            "flagged_qty": new_flagged_qty,
            "racked_qty": 0,
            "uom": box_item.uom,
        })

    if quality_check.is_new():
        quality_check.insert(ignore_permissions=True)
    else:
        quality_check.save(ignore_permissions=True)

    # Update verified quantity in Box Item.
    frappe.db.set_value(
        "Box Items",
        box_item.name,
        "verified_qty",
        new_verified_qty,
        update_modified=False,
    )

    box_item.verified_qty = new_verified_qty

    # Calculate total verified quantity from Box Items.
    total_verified_qty = sum(
        int(row.verified_qty or 0)
        for row in box.items
    )

    frappe.db.set_value(
        "Box",
        box_id,
        "verified_items",
        total_verified_qty,
        update_modified=False,
    )

    # Check whether all Item quantities are verified or flagged.
    verified_items = {
        row.item: row
        for row in quality_check.items
        if row.box == box_id
    }

    is_box_verified = bool(box_items) and all(
        item in verified_items
        and verified_items[item].verified_qty == row.qty
        for item, row in box_items.items()
    )

    if is_box_verified:
        # Get Box row from the already loaded Packing List.
        packing_box = next(
            row for row in packing_doc.items
            if row.box_id == box_id
        )

        frappe.db.set_value(
            "Packing List Box",
            packing_box.name,
            "is_verified",
            1,
            update_modified=False,
        )

        packing_box.is_verified = 1

        # Calculate verified Box count from child table.
        verified_boxes = sum(
            int(row.is_verified or 0)
            for row in packing_doc.items
        )

        frappe.db.set_value(
            "Packing List",
            packing_list,
            "verified_boxes",
            verified_boxes,
            update_modified=False,
        )

    return {
        "draft_quality_check": quality_check.name,
        "message": _("Box Item verification created successfully."),
    }


@frappe.whitelist(methods=["POST"])
def complete_box_verification(data=None):
    """Validate and submit a draft Stock Quality Check."""

    data = frappe.parse_json(data) if data else frappe.form_dict

    stock_quality_check = data.get("stock_quality_check")
    quality_check = frappe.get_doc("Stock Quality Check", stock_quality_check)

    packing_boxes = frappe.get_all(
        "Packing List Box",
        filters={
            "parent": quality_check.packing_list,
            "parenttype": "Packing List",
            "parentfield": "items",
            "is_received": 1,
        },
        fields=["box_id", "is_verified"],
    )

    unverified_boxes = [
        row.box_id for row in packing_boxes if not row.is_verified
    ]

    if unverified_boxes:
        frappe.throw(
            _("Verification is incomplete for Boxes: {0}").format(
                ", ".join(unverified_boxes)
            )
        )

    expected_items = {}

    for packing_box in packing_boxes:
        box = frappe.get_doc("Box", packing_box.box_id)

        for row in box.items:
            expected_items[(packing_box.box_id, row.item)] = row.qty

    verified_items = set()

    for row in quality_check.items:
        key = (row.box, row.item)
        verified_items.add(key)

        if row.verified_qty != expected_items[key]:
            frappe.throw(
                _("Verification is incomplete for Item {0} in Box {1}.").format(
                    row.item, row.box
                )
            )

    missing_items = set(expected_items) - verified_items

    if missing_items:
        box_id, item_code = sorted(missing_items)[0]

        frappe.throw(
            _("Verification is incomplete for Item {0} in Box {1}.").format(
                item_code, box_id
            )
        )

    quality_check.submit()

    return {
        "stock_quality_check": quality_check.name,
        "message": _("Stock Quality Check submitted successfully."),
    }