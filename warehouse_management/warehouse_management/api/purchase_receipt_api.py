# Copyright (c) 2026, Rakonex and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import cint
from frappe.utils.file_manager import get_file_path
from pathlib import Path


@frappe.whitelist(methods=["GET"])
def get_purchase_orders():
    """Return pending Purchase Orders for the logged-in user's warehouse."""

    employee = frappe.db.get_value(
        "Employee",
        {"user_id": frappe.session.user, "status": "Active"},
        "active_warehouse"
    )

    if not employee:
        frappe.throw(_("No active warehouse assigned to the logged-in user."))

    purchase_orders = frappe.get_list(
        "Purchase Order",
        filters={
            "status": ["in", ["To Receive and Bill", "To Receive"]],
            "set_warehouse": employee
        },
        fields=[
            "name",
            "supplier",
            "supplier_name",
            "per_received",
            "supplier_pack_list"
        ],
        limit_page_length=0
    )

    for po in purchase_orders:
        po.supplier_pack_list = bool(po.supplier_pack_list)

    frappe.response["data"] = purchase_orders


@frappe.whitelist(methods=["GET"])
def get_po_supplier_pack_list(purchase_order, download=0):
    """Return Supplier Pack List details or download the attachment."""

    po = frappe.get_doc("Purchase Order", purchase_order)
    po.check_permission("read")

    if not po.supplier_pack_list:
        return None

    file = frappe.db.get_value(
        "File",
        {
            "file_url": po.supplier_pack_list,
            "attached_to_doctype": "Purchase Order",
            "attached_to_name": po.name
        },
        ["name", "file_name", "file_url", "is_private"],
        as_dict=True
    )

    if not file:
        frappe.throw(_("Attached file not found."))

    if cint(download):
        file_path = Path(get_file_path(file.file_url))

        if not file_path.is_file():
            frappe.throw(_("Attached file not found."))

        frappe.local.response.filename = file.file_name
        frappe.local.response.filecontent = file_path.read_bytes()
        frappe.local.response.type = "download"
        return

    return {
        "purchase_order": po.name,
        "file_name": file.file_name,
        "is_private": bool(file.is_private),
        "file": file.name
    }


@frappe.whitelist(methods=["POST"])
def create_purchase_receipt_from_po():
	"""
	Create a Purchase Receipt in draft status from a Purchase Order.
	Creates new Item template if item has surprise_variant enabled.
	"""

	try:
		# Get request data
		data = frappe.local.request.get_json()

		warehouse = data.get("warehouse")
		items_data = data.get("items", [])

		if not items_data:
			frappe.throw("Items data is required")

		po_names = list({
			item.get("po_id")
			for item in items_data
			if item.get("po_id")
		})

		if not po_names:
			frappe.throw("At least one Purchase Order is required")

		po_details = frappe.get_all(
			"Purchase Order",
			filters={"name": ["in", po_names]},
			fields=["name", "supplier", "supplier_name"]
		)

		if len(po_details) != len(po_names):
			frappe.throw("One or more Purchase Orders were not found")

		supplier_set = {po.supplier for po in po_details}

		if len(supplier_set) > 1:
			frappe.throw("All selected Purchase Orders must belong to the same supplier.")

		supplier = po_details[0].supplier

		if not warehouse:
			frappe.throw("Warehouse is required")

		# Create Purchase Receipt
		pr = frappe.get_doc({
			"doctype": "Purchase Receipt",
			"supplier": supplier,
			"posting_date": frappe.utils.today(),
			"warehouse": warehouse,
			"items": []
		})

		# Create PO item lookup map
		po_items = frappe.get_all(
			"Purchase Order Item",
			filters={"parent": ["in", po_names]},
			fields=[
				"name",
				"parent",
				"item_code",
				"qty",
				"uom",
				"stock_uom",
				"rate"
			]
		)

		po_items_map = {
			(item.parent, item.item_code): item
			for item in po_items
		}

		# Process incoming items
		for item_data in items_data:

			po_id = item_data.get("po_id")
			item_code = item_data.get("item_code")

			if not po_id:
				frappe.throw("PO ID is required for all items")

			if not item_code:
				frappe.throw("Item code is required for all items")

			po_item = po_items_map.get((po_id, item_code))

			if not po_item:
				frappe.throw(f"Item {item_code} not found in Purchase Order {po_id}")

			# ----------------------------------------------------------
			# Create Item Template if surprise variant is enabled
			# ----------------------------------------------------------
			if item_data.get("surprise_variant"):

				variant_attributes = item_data.get("variant_attribute")

				if not variant_attributes:
					frappe.throw(
						f"variant_attribute is required when surprise_variant is enabled for item {item_code}"
					)

				if not isinstance(variant_attributes, list):
					frappe.throw(f"variant_attribute must be a list for item {item_code}")

				template_item_code = f"{item_code}-T"

				# Create template only if it doesn't already exist
				if not frappe.db.exists("Item", template_item_code):

					source_item = frappe.get_doc("Item", item_code)

					template_item = frappe.copy_doc(source_item)

					# Reset identifiers
					template_item.name = None

					# Convert copied item into template
					template_item.item_code = template_item_code
					template_item.item_name = (
						f"{source_item.item_name} - Template"
					)

					template_item.has_variants = 1
					template_item.variant_based_on = "Item Attribute"

					# Remove any existing attributes
					template_item.attributes = []

					# Add requested attributes
					for attribute in variant_attributes:

						if not attribute:
							continue

						template_item.append(
							"attributes",
							{
								"attribute": attribute
							}
						)

					if not template_item.attributes:
						frappe.throw(f"At least one valid variant attribute is required for item {item_code}")

					template_item.insert(ignore_permissions=True)

			# ----------------------------------------------------------
			# Create Purchase Receipt Item
			# ----------------------------------------------------------

			# Determine target warehouse
			target_warehouse = warehouse

			if item_data.get("surprise_variant"):
				target_warehouse = f"Bay {warehouse}"

			pr_item = {
				"item_code": item_code,
				"qty": item_data.get("quantity", po_item.qty),
				"uom": item_data.get("uom", po_item.uom),
				"rate": po_item.rate,
				"purchase_order": po_id,
				"purchase_order_item": po_item.name,
				"received_qty": item_data.get(
					"quantity",
					po_item.qty
				),
				"warehouse": target_warehouse,
				"rack": item_data.get("rack"),
				"bin": item_data.get("bin"),
				"expiry_date": item_data.get("expiry_date"),
				"stock_uom": (
					po_item.stock_uom
					if hasattr(po_item, "stock_uom")
					else po_item.uom
				),
			}

			pr.append("items", pr_item)

		# Save PR in draft status
		pr.insert(ignore_permissions=True)

		frappe.db.commit()

		return {
			"status": "success",
			"message": "Purchase Receipt created successfully",
			"data": {
				"name": pr.name,
				"doctype": "Purchase Receipt",
				"status": pr.docstatus
			}
		}

	except frappe.ValidationError as e:
		frappe.log_error(
			frappe.get_traceback(),
			"Purchase Receipt Creation Error"
		)

		return {
			"status": "error",
			"message": f"Validation Error: {str(e)}",
			"data": None
		}

	except Exception as e:
		frappe.log_error(
			frappe.get_traceback(),
			"Purchase Receipt Creation Error"
		)

		return {
			"status": "error",
			"message": f"Error creating Purchase Receipt: {str(e)}",
			"data": None
		}
