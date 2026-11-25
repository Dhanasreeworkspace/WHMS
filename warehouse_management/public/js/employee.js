frappe.ui.form.on("Employee", {
    refresh(frm) {
        set_main_warehouse_query(frm, "active_warehouse");
    },
});