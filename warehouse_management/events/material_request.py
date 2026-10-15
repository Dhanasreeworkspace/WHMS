import frappe
from frappe import _

from warehouse_management.utils import get_sub_warehouses, get_main_warehouse
from warehouse_management.events.stock_availability import get_available_qty_for_items


def notify_warehouse_manager(doc, method=None):
    if doc.material_request_type != "Material Transfer":
        return

    if not doc.has_value_changed("workflow_state"):
        return

    if doc.workflow_state == "Pending":
        notify_source_warehouse_manager(doc)

    elif doc.workflow_state in ("Approved", "Rejected"):
        notify_target_warehouse_manager(doc)


def notify_source_warehouse_manager(doc, method=None):
    """Notify Warehouse Managers when MR is pending for approval."""

    source_warehouses = {
        row.from_warehouse
        for row in doc.items
        if row.from_warehouse
    }

    manager_warehouses = {
        get_main_warehouse(warehouse)
        for warehouse in source_warehouses
    }

    manager_warehouses.discard(None)

    for user in get_warehouse_manager_users(manager_warehouses):
        frappe.get_doc(
            {
                "doctype": "Notification Log",
                "subject": f"Material Request {doc.name} Requires Approval",
                "email_content": (
                    f"Material Request {doc.name} is awaiting your approval. "
                    "Please review and take the required action."
                ),
                "for_user": user,
                "type": "Alert",
                "document_type": "Material Request",
                "document_name": doc.name,
            }
        ).insert(ignore_permissions=True)


def notify_target_warehouse_manager(doc, method=None):
    """
    Notify Warehouse Managers whose active_warehouse matches
    the target warehouse of the approved Material Request.
    """

    target_warehouses = {
        row.warehouse
        for row in doc.items
        if row.warehouse
    }

    manager_warehouses = {
        get_main_warehouse(warehouse)
        for warehouse in target_warehouses
    }

    manager_warehouses.discard(None)

    for user in get_warehouse_manager_users(manager_warehouses):
        frappe.get_doc(
            {
                "doctype": "Notification Log",
                "subject": (
                    f"Material Request {doc.name} "
                    f"{doc.workflow_state}"
                ),
                "email_content": (
                    f"Material Request {doc.name} has been "
                    f"{doc.workflow_state}."
                ),
                "for_user": user,
                "type": "Alert",
                "document_type": "Material Request",
                "document_name": doc.name,
            }
        ).insert(ignore_permissions=True)


def get_warehouse_manager_users(warehouses):
    if not warehouses:
        return []

    employees = frappe.get_all(
        "Employee",
        filters={
            "status": "Active",
            "active_warehouse": ["in", list(warehouses)],
        },
        fields=["user_id"],
    )

    users = []

    for employee in employees:
        if not employee.user_id:
            continue

        roles = frappe.get_roles(employee.user_id)

        if "Warehouse Manager" not in roles:
            continue

        if "System Manager" in roles:
            continue

        users.append(employee.user_id)

    return list(set(users))


def get_manager_details(user):
    return frappe.db.get_value(
        "Employee",
        {
            "user_id": user,
            "status": "Active",
        },
        ["active_warehouse", "allow_access_to_all_warehouses"],
        as_dict=True,
    )


def validate_warehouse_manager(doc, method=None):
    """Allow only the source Warehouse Manager to approve or reject."""

    if doc.material_request_type != "Material Transfer":
        return

    if not doc.has_value_changed("workflow_state"):
        return

    old_doc = doc.get_doc_before_save()

    if not old_doc or old_doc.workflow_state != "Pending":
        return

    if doc.workflow_state not in ("Approved", "Rejected"):
        return
    
    user = frappe.session.user
    roles = frappe.get_roles(user)

    if "System Manager" in roles:
        return

    if "Warehouse Manager" not in roles:
        return

    employee = get_manager_details(user)

    if not employee:
        frappe.throw(
            _("You cannot approve or reject this Material Request.")
        )

    if employee.allow_access_to_all_warehouses:
        return

    if not employee.active_warehouse:
        frappe.throw(
            _("You cannot approve or reject this Material Request.")
        )

    managed_warehouses = set(
        get_sub_warehouses(employee.active_warehouse)
    )

    source_warehouses = {
        row.from_warehouse
        for row in doc.items
        if row.from_warehouse
    }

    if not source_warehouses.intersection(managed_warehouses):
        frappe.throw(
            _("You cannot approve or reject this Material Request.")
        )


def get_permission_query_conditions(user=None):
    user = user or frappe.session.user
    roles = frappe.get_roles(user)

    if "System Manager" in roles:
        return ""

    if "Warehouse Manager" not in roles:
        return ""

    employee = get_manager_details(user)

    if not employee:
        return "1=0"
    
    if employee.allow_access_to_all_warehouses:
        return ""
    
    if not employee.active_warehouse:
        return "1=0"

    managed_warehouses = get_sub_warehouses(
        employee.active_warehouse,
        include_sub_warehouses=True,
    )

    if not managed_warehouses:
        return "1=0"

    warehouses = ", ".join(
        frappe.db.escape(warehouse)
        for warehouse in managed_warehouses
    )

    return f"""
        EXISTS (
            SELECT 1
            FROM `tabMaterial Request Item` AS mr_item
            WHERE
                mr_item.parent = `tabMaterial Request`.name
                AND mr_item.parenttype = 'Material Request'
                AND (
                    mr_item.warehouse IN ({warehouses})
                    OR mr_item.from_warehouse IN ({warehouses})
                )
        )
    """


@frappe.whitelist()
def get_active_warehouse():
    roles = frappe.get_roles(frappe.session.user)

    if "System Manager" in roles:
        return None

    if "Warehouse Manager" not in roles:
        return None

    employee = frappe.db.get_value(
        "Employee",
        {
            "user_id": frappe.session.user,
            "status": "Active",
        },
        "active_warehouse",
    )

    return employee


def update_stock_available_at_source(doc, method=None):
    """Update source stock for Material Request items on save.
    Stock is summed from the source warehouse and included sub-warehouses.
    """
    if doc.material_request_type != "Material Transfer":
        return

    if doc.docstatus != 0:
        return

    warehouse = doc.set_from_warehouse

    if not warehouse:
        for item in doc.items:
            item.stock_available_at_source = 0
        return

    item_codes = list({
        item.item_code
        for item in doc.items
        if item.item_code
    })

    if not item_codes:
        return

    stock_map = get_available_qty_for_items(item_codes, warehouse)

    for item in doc.items:
        item.stock_available_at_source = (
            stock_map.get(item.item_code, 0)
            if item.item_code
            else 0
        )

@frappe.whitelist()
def get_conflicting_pending_mrs(material_request):
    mr = frappe.get_doc("Material Request", material_request)

    item_codes = [d.item_code for d in mr.items]
    source_warehouse = mr.set_from_warehouse

    if not item_codes or not source_warehouse:
        return []

    conflicts = frappe.db.sql("""
        SELECT
            mr.name AS mr_name,
            mr.set_warehouse AS target_warehouse,
            mri.item_code,
            mri.item_name,
            mri.qty
        FROM `tabMaterial Request` mr
        INNER JOIN `tabMaterial Request Item` mri ON mri.parent = mr.name
        WHERE mr.workflow_state = 'Pending'
          AND mr.name != %(mr_name)s
          AND mr.set_from_warehouse = %(source_warehouse)s
          AND mri.item_code IN %(item_codes)s
    """, {
        "mr_name": material_request,
        "source_warehouse": source_warehouse,
        "item_codes": item_codes
    }, as_dict=True)

    return conflicts