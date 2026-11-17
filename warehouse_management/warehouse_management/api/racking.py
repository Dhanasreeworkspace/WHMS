import frappe
from frappe import _
from frappe.utils import flt


@frappe.whitelist(methods=["GET"])
def get_racking_stock_quality_checks(warehouse):
    """Return submitted Stock Quality Checks pending racking."""

    quality_checks = frappe.get_all(
        "Stock Quality Check",
        filters={
            "docstatus": 1,
            "destination_warehouse": warehouse,
        },
        fields=[
            "name",
            "material_request",
            "pick_list",
            "warehouse",
            "destination_warehouse",
            "total_qc_passed",
            "total_racked",
        ],
        order_by="creation desc",
    )

    result = []

    for row in quality_checks:
        total_qc_passed = flt(row.total_qc_passed)
        total_racked = flt(row.total_racked)

        if total_qc_passed <= 0:
            continue

        draft_stock_entry = frappe.db.get_value(
            "Stock Entry",
            {
                "material_request": row.material_request,
                "pick_list": row.pick_list,
                "stock_entry_type": "Material Transfer",
                "from_warehouse": row.warehouse,
                "to_warehouse": row.destination_warehouse,
                "docstatus": 0,
            },
            "name",
        )

        if total_racked >= total_qc_passed and not draft_stock_entry:
            continue

        result.append({
            "stock_quality_check": row.name,
            "material_request": row.material_request,
            "stock_entry": draft_stock_entry,
            "racking_status": (
                "In Progress" if total_racked > 0 else "To Start"
            ),
        })

    return result


@frappe.whitelist(methods=["GET"])
def get_racking_sqc_items(stock_quality_check, item_code=None, barcode=None):
    """Return aggregated SQC items with optional item/barcode filtering."""

    sqc = frappe.get_doc("Stock Quality Check", stock_quality_check)

    # Find item using barcode.
    if barcode:
        item_code = frappe.db.get_value(
            "Item Barcode",
            {"barcode": barcode},
            "parent",
        )

    # Filter SQC items.
    quality_items = [
        row for row in sqc.items
        if not item_code or row.item == item_code
    ]

    item_codes = list({row.item for row in quality_items})

    # Fetch item details.
    item_details = dict(
        frappe.get_all(
            "Item",
            filters={"name": ["in", item_codes]},
            fields=["name", "item_name"],
            as_list=True,
        )
    ) if item_codes else {}

    # Fetch barcodes.
    barcodes = frappe.get_all(
        "Item Barcode",
        filters={"parent": ["in", item_codes]},
        fields=["parent", "barcode"],
        order_by="idx asc",
    ) if item_codes else []

    barcode_map = {}

    for row in barcodes:
        barcode_map.setdefault(row.parent, row.barcode)

    # Aggregate item quantities across boxes.
    items_map = {}

    for row in quality_items:
        if row.item not in items_map:
            items_map[row.item] = {
                "item_code": row.item,
                "item_name": item_details.get(row.item),
                "barcode": barcode_map.get(row.item),
                "verified_qty": 0,
                "qc_passed_qty": 0,
                "flagged_qty": 0,
                "racked_qty": 0,
            }

        item = items_map[row.item]

        item["verified_qty"] += flt(row.verified_qty)
        item["qc_passed_qty"] += flt(row.qc_passed_qty)
        item["flagged_qty"] += flt(row.flagged_qty)
        item["racked_qty"] += flt(row.racked_qty)

    # Find existing Racking Stock Entry.
    stock_entry_name = frappe.db.get_value(
        "Stock Entry",
        {
            "material_request": sqc.material_request,
            "pick_list": sqc.pick_list,
            "stock_entry_type": "Material Transfer",
            "from_warehouse": sqc.warehouse,
            "to_warehouse": sqc.destination_warehouse,
            "docstatus": 0,
        },
        "name",
    )

    # Get bins containing the item in the destination warehouse.
    if item_code and item_code in items_map:
        storage_bin_items = frappe.get_all(
            "Storage Bin Item",
            filters={
                "item": item_code,
                "quantity": [">", 0],
                "parenttype": "Storage Bin",
            },
            fields=["parent", "quantity"],
        )

        bin_names = [row.parent for row in storage_bin_items]

        storage_bins = {
            row.name: row
            for row in frappe.get_all(
                "Storage Bin",
                filters={
                    "name": ["in", bin_names],
                    "warehouse": sqc.destination_warehouse,
                },
                fields=["name", "rack"],
            )
        } if bin_names else {}

        items_map[item_code]["bin_history"] = [
            {
                "rack": storage_bins[row.parent].rack,
                "bin": row.parent,
                "qty": flt(row.quantity),
            }
            for row in storage_bin_items
            if row.parent in storage_bins
        ]

    return {
        "stock_quality_check": sqc.name,
        "stock_entry": stock_entry_name,
        "total_verified": flt(sqc.total_verified),
        "total_qc_passed": flt(sqc.total_qc_passed),
        "total_racked": flt(sqc.total_racked),
        "items": list(items_map.values()),
    }


@frappe.whitelist(methods=["POST"])
def move_item_to_storage(data=None):
    """Allocate verified items to racks/bins using a draft Stock Entry."""

    data = frappe.parse_json(data) if data else frappe.form_dict

    stock_quality_check = data.get("stock_quality_check")
    item_code = data.get("item_code")
    allocations = frappe.parse_json(data.get("allocations") or [])

    sqc = frappe.get_doc("Stock Quality Check", stock_quality_check)

    quality_items = [row for row in sqc.items if row.item == item_code]

    total_qc_passed_qty = sum(flt(row.qc_passed_qty) for row in quality_items)
    total_racked_qty = sum(flt(row.racked_qty) for row in quality_items)
    remaining_qty = total_qc_passed_qty - total_racked_qty

    # --------------------------------------------------
    # Fetch Storage Bins
    # --------------------------------------------------

    bin_names = {
        allocation.get("bin")
        for allocation in allocations
        if allocation.get("bin")
    }

    storage_bins = {
        row.name: row
        for row in frappe.get_all(
            "Storage Bin",
            filters={"name": ["in", list(bin_names)]},
            fields=["name", "rack", "warehouse"],
        )
    }

    # --------------------------------------------------
    # Group Allocations by Rack/Bin
    # --------------------------------------------------

    grouped_allocations = {}

    for allocation in allocations:
        rack = allocation.get("rack")
        bin_name = allocation.get("bin")
        qty = flt(allocation.get("qty"))

        bin_doc = storage_bins.get(bin_name)

        if bin_doc.rack != rack:
            frappe.throw(
                _("Bin {0} does not belong to Rack {1}.").format(
                    bin_name, rack
                )
            )

        if bin_doc.warehouse != sqc.destination_warehouse:
            frappe.throw(
                _("Bin {0} does not belong to Warehouse {1}.").format(
                    bin_name, sqc.destination_warehouse
                )
            )

        key = (rack, bin_name)
        grouped_allocations[key] = (grouped_allocations.get(key, 0) + qty)

    total_qty = sum(grouped_allocations.values())

    if total_qty > remaining_qty:
        frappe.throw(
            _(
                "Cannot rack {0} units of Item {1}. "
                "Remaining quantity is {2}."
            ).format(total_qty, item_code, remaining_qty)
        )

    # --------------------------------------------------
    # Find Existing Racking Stock Entry
    # --------------------------------------------------

    draft_stock_entry = frappe.db.get_value(
        "Stock Entry",
        {
            "material_request": sqc.material_request,
            "pick_list": sqc.pick_list,
            "stock_entry_type": "Material Transfer",
            "from_warehouse": sqc.warehouse,
            "to_warehouse": sqc.destination_warehouse,
            "docstatus": 0,
        },
        "name",
    )

    if draft_stock_entry:
        stock_entry = frappe.get_doc("Stock Entry", draft_stock_entry)
    else:
        stock_entry = frappe.new_doc("Stock Entry")
        stock_entry.stock_entry_type = "Material Transfer"
        stock_entry.material_request = sqc.material_request
        stock_entry.pick_list = sqc.pick_list
        stock_entry.from_warehouse = sqc.warehouse
        stock_entry.to_warehouse = sqc.destination_warehouse

        stock_entry.company = frappe.db.get_value(
            "Warehouse",
            sqc.destination_warehouse,
            "company",
        )

    # --------------------------------------------------
    # Get MR Item and Pick List Item References
    # --------------------------------------------------

    mr_items = frappe.get_all(
        "Material Request Item",
        filters={
            "parent": sqc.material_request,
            "item_code": item_code,
        },
        pluck="name",
    )

    material_request_item = (mr_items[0] if len(mr_items) == 1 else None)

    pick_list_items = frappe.get_all(
        "Pick List Item",
        filters={
            "parent": sqc.pick_list,
            "item_code": item_code,
        },
        pluck="name",
    )

    pick_list_item = (
        pick_list_items[0]
        if len(pick_list_items) == 1
        else None
    )

    # --------------------------------------------------
    # Index Existing Stock Entry Items
    # --------------------------------------------------

    existing_items = {}

    for row in stock_entry.items:
        if row.item_code != item_code:
            continue

        key = (row.rack, row.bin)

        if key in existing_items:
            frappe.throw(
                _(
                    "Duplicate Stock Entry rows exist for "
                    "Item {0}, Rack {1}, Bin {2}."
                ).format(item_code, row.rack, row.bin)
            )

        existing_items[key] = row

    # --------------------------------------------------
    # Create/Update Stock Entry Items
    # --------------------------------------------------

    for (rack, bin_name), qty in grouped_allocations.items():
        existing_item = existing_items.get((rack, bin_name))

        if existing_item:
            existing_item.qty = flt(existing_item.qty) + qty

        else:
            item_data = {
                "item_code": item_code,
                "qty": qty,
                "uom": quality_items[0].uom,
                "s_warehouse": sqc.warehouse,
                "t_warehouse": sqc.destination_warehouse,
                "rack": rack,
                "bin": bin_name,
            }

            if material_request_item:
                item_data["material_request_item"] = material_request_item

            if pick_list_item:
                item_data["pick_list_item"] = pick_list_item

            stock_entry.append("items", item_data)

    # Save Draft Stock Entry
    if stock_entry.is_new():
        stock_entry.insert(ignore_permissions=True)
    else:
        stock_entry.save(ignore_permissions=True)

    # --------------------------------------------------
    # Update SQC Item Racked Quantities
    # --------------------------------------------------

    pending_qty = total_qty

    for quality_item in quality_items:
        available_qty = flt(quality_item.qc_passed_qty) - flt(quality_item.racked_qty)

        if available_qty <= 0:
            continue

        allocated_qty = min(pending_qty, available_qty)

        if allocated_qty <= 0:
            continue

        frappe.db.set_value(
            "Stock Quality Check Item",
            quality_item.name,
            "racked_qty",
            flt(quality_item.racked_qty) + allocated_qty,
            update_modified=False,
        )

        pending_qty -= allocated_qty

        if pending_qty <= 0:
            break

    # --------------------------------------------------
    # Update Parent Total Racked
    # --------------------------------------------------

    new_total_racked = flt(sqc.total_racked) + total_qty

    if new_total_racked > flt(sqc.total_qc_passed):
        frappe.throw(
            _("Total Racked Qty cannot exceed Total QC Passed Qty.")
        )

    frappe.db.set_value(
        "Stock Quality Check",
        sqc.name,
        "total_racked",
        new_total_racked,
        update_modified=False,
    )

    new_racked_qty = total_racked_qty + total_qty

    return {
        "stock_quality_check": sqc.name,
        "draft_stock_entry": stock_entry.name,
        "item_code": item_code,
        "racked_qty": new_racked_qty,
        "to_rack_qty": max(total_qc_passed_qty - new_racked_qty, 0),
        "message": _("Item allocated to Rack and Bin successfully."),
    }


@frappe.whitelist(methods=["POST"])
def complete_racking(data=None):
    """Validate and submit a draft racking Stock Entry."""

    data = frappe.parse_json(data) if data else frappe.form_dict

    stock_entry = frappe.get_doc("Stock Entry", data.get("stock_entry"))

    if stock_entry.docstatus != 0:
        frappe.throw(_("Stock Entry must be in Draft status."))

    # Validate racking Stock Entry.
    if (
        stock_entry.stock_entry_type != "Material Transfer"
        or not stock_entry.material_request
        or not stock_entry.pick_list
        or not stock_entry.from_warehouse
        or not stock_entry.to_warehouse
    ):
        frappe.throw(_("Invalid racking Stock Entry."))

    if not stock_entry.items:
        frappe.throw(_("No items found in the Stock Entry."))

    # Get Bay Storage Bin from the source warehouse.
    bay_bin = frappe.db.get_value(
        "Storage Bin",
        {"warehouse": stock_entry.from_warehouse},
        ["name", "rack"],
        as_dict=True,
    )

    if not bay_bin:
        frappe.throw(
            _("Storage Bin not found for Bay Warehouse {0}.").format(
                stock_entry.from_warehouse
            )
        )

    for row in stock_entry.items:
        if flt(row.qty) <= 0:
            frappe.throw(
                _("Invalid racking quantity for Item {0}.").format(
                    row.item_code
                )
            )

    stock_entry.submit()

    # Create Picking assignments to deduct quantities from Bay.
    for row in stock_entry.items:
        frappe.get_doc({
            "doctype": "Bin Assignment",
            "assignment_type": "Picking",
            "stock_entry": stock_entry.name,
            "material_request": stock_entry.material_request,
            "item": row.item_code,
            "rack": bay_bin.rack,
            "bin": bay_bin.name,
            "uom": row.uom,
            "quantity": row.transfer_qty or row.qty,
            "batch_no": row.get("batch_no"),
            "notes": f"Racking transfer from Bay {stock_entry.name}",
        }).insert(ignore_permissions=True)

    return {
        "stock_entry": stock_entry.name,
        "message": _("Racking Stock Entry submitted successfully."),
    }