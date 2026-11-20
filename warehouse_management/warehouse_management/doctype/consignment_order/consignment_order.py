import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import today


class ConsignmentOrder(Document):

    def on_submit(self):
        self.create_material_request()

    def create_material_request(self):
        """Create a draft Material Transfer Request from CSO."""

        if not self.items:
            frappe.throw(_("Please add items before submitting."))

        if not self.source_warehouse or not self.warehouse:
            frappe.throw(_("Source and Target Warehouses are required."))

        if self.source_warehouse == self.warehouse:
            frappe.throw(_("Source and Target Warehouses cannot be the same."))

        # Prevent duplicate Material Request creation
        if frappe.db.exists("Material Request", {
            "consignment_order": self.name
        }):
            return
        # Get the company of both warehouses.
        
        company = frappe.db.get_value(
            "Warehouse", self.warehouse, "company"
        )

        source_company = frappe.db.get_value(
            "Warehouse", self.source_warehouse, "company"
        )

        if not company or company != source_company:
            frappe.throw(
                _("Source and Target Warehouses must belong to the same company.")
            )

        schedule_date = self.required_by_date or today()

        material_request = frappe.get_doc({
            "doctype": "Material Request",
            "material_request_type": "Material Transfer",
            "company": company,
            "transaction_date": self.date or today(),
            "schedule_date": schedule_date,
            "set_from_warehouse": self.source_warehouse,
            "set_warehouse": self.warehouse,
            "is_consignment": 1,
            "consignment_order": self.name,
            "items": []
        })

        for row in self.items:

            if not row.item_code or not row.quantity or row.quantity <= 0:
                frappe.throw(
                    _("Invalid item or quantity in row {0}.").format(row.idx)
                )

            item = frappe.get_cached_value(
                "Item",
                row.item_code,
                ["stock_uom", "is_stock_item"],
                as_dict=True
            )

            if not item or not item.is_stock_item:
                frappe.throw(
                    _("Item {0} must be a valid stock item.").format(row.item_code)
                )

            material_request.append("items", {
                "item_code": row.item_code,
                "qty": row.quantity,
                "uom": item.stock_uom,
                "stock_uom": item.stock_uom,
                "conversion_factor": 1,
                "schedule_date": schedule_date,
                "from_warehouse": self.source_warehouse,
                "warehouse": self.warehouse
            })

        material_request.insert(ignore_permissions=True)

        return material_request.name