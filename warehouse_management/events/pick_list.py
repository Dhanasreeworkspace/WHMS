import frappe
from frappe import _
from frappe.utils import flt

from warehouse_management.utils import get_main_warehouse
from warehouse_management.events.material_request import get_warehouse_manager_users


def validate_material_requests(doc, method=None):
    """Validate linked Material Request and picking completion."""

    if doc.purpose != "Material Transfer" or not doc.material_request:
        return

    mr = frappe.get_doc("Material Request", doc.material_request)

    if mr.workflow_state != "Approved":
        frappe.throw(
            _("Only Approved Material Requests can be linked to a Pick List.")
        )

    existing_pick_list = frappe.db.exists(
        "Pick List",
        {
            "material_request": mr.name,
            "docstatus": ["<", 2],
            "name": ["!=", doc.name],
        },
    )

    if existing_pick_list:
        frappe.throw(
            _("Another Pick List already exists for Material Request {0}.")
            .format(mr.name)
        )

    if method != "before_submit":
        return

    mr_items = {row.name: row for row in mr.items}
    picked_qty = {}

    for row in doc.locations:
        mr_item = mr_items.get(row.material_request_item)

        if not mr_item:
            frappe.throw(
                _("Invalid Material Request Item for Item {0}.")
                .format(row.item_code)
            )

        if row.item_code != mr_item.item_code:
            frappe.throw(
                _("Pick List Item does not match Material Request Item.")
            )

        picked_qty[row.material_request_item] = (
            picked_qty.get(row.material_request_item, 0)
            + flt(row.qty)
        )

    for row in mr.items:
        picked = flt(picked_qty.get(row.name, 0))
        required = flt(row.qty)

        if picked > required:
            frappe.throw(
                _("Picked quantity exceeds requested quantity for Item {0}.")
                .format(row.item_code)
            )

        if picked < required and not row.is_picking_skipped:
            frappe.throw(
                _(
                    "Item {0} is not fully picked. "
                    "Complete picking or mark Is Picking Skipped."
                ).format(row.item_code)
            )


def update_material_request_picking_status(material_request):
    """Update MR workflow state after Pick List submission."""

    mr = frappe.get_doc("Material Request", material_request)
    previous_state = mr.workflow_state

    pick_lists = frappe.get_all(
        "Pick List",
        filters={
            "material_request": mr.name,
            "docstatus": 1,
        },
        pluck="name",
    )

    if not pick_lists:
        return

    locations = frappe.get_all(
        "Pick List Item",
        filters={
            "parent": ["in", pick_lists],
            "parenttype": "Pick List",
            "parentfield": "locations",
        },
        fields=["material_request_item", "qty"],
    )

    picked = {}

    for row in locations:
        picked[row.material_request_item] = (
            picked.get(row.material_request_item, 0)
            + flt(row.qty)
        )

    fully_picked = all(
        flt(picked.get(row.name, 0)) >= flt(row.qty)
        for row in mr.items
    )

    workflow_state = (
        "Picked" if fully_picked else "Partially Picked"
    )

    frappe.db.set_value(
        "Material Request",
        mr.name,
        "workflow_state",
        workflow_state,
        update_modified=False,
    )

    # Notify source warehouse manager when the MR becomes Partially Picked.
    if (
        workflow_state == "Partially Picked"
        and previous_state != "Partially Picked"
    ):
        notify_source_warehouse_manager_partial_picking(mr)


def update_material_requests_as_picked(doc, method=None):
    """Recalculate MR picking status after Pick List submission."""

    material_requests = {
        row.material_request
        for row in doc.locations
        if row.material_request
    }

    for material_request in material_requests:
        update_material_request_picking_status(material_request)


def revert_material_requests_to_approved(doc, method=None):
    """Recalculate MR picking status after Pick List cancellation."""

    material_requests = {
        row.material_request
        for row in doc.locations
        if row.material_request
    }

    for material_request in material_requests:
        current_state = frappe.db.get_value(
            "Material Request",
            material_request,
            "workflow_state",
        )

        if current_state not in [
            "Approved",
            "Partially Picked",
            "Picked",
        ]:
            continue

        pick_lists = frappe.get_all(
            "Pick List",
            filters={
                "material_request": material_request,
                "docstatus": 1,
            },
            pluck="name",
        )

        if not pick_lists:
            frappe.db.set_value(
                "Material Request",
                material_request,
                "workflow_state",
                "Approved",
                update_modified=False,
            )
        else:
            update_material_request_picking_status(material_request)


def delete_bin_assignments_on_pick_list_cancel(doc, method=None):
    bin_assignments = frappe.get_all(
        "Bin Assignment",
        filters={
            "pick_list": doc.name,
            "assignment_type": "Picking",
        },
        pluck="name",
    )

    for bin_assignment in bin_assignments:
        frappe.delete_doc(
            "Bin Assignment",
            bin_assignment,
            ignore_permissions=True,
        )


def notify_source_warehouse_manager_partial_picking(doc):
    """Notify source Warehouse Managers when an MR is partially picked."""

    if doc.material_request_type != "Material Transfer":
        return

    source_warehouse = doc.set_from_warehouse

    if not source_warehouse:
        return

    manager_warehouse = get_main_warehouse(source_warehouse)

    if not manager_warehouse:
        return

    users = get_warehouse_manager_users({manager_warehouse})

    for user in users:
        frappe.get_doc({
            "doctype": "Notification Log",
            "subject": f"Material Request {doc.name} Partially Picked",
            "email_content": (
                f"Items from {doc.name} has been partially picked "
                f"from warehouse {source_warehouse}. "
                "Please take note of the updated picking status."
            ),
            "for_user": user,
            "type": "Alert",
            "document_type": "Material Request",
            "document_name": doc.name,
        }).insert(ignore_permissions=True)