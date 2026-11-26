frappe.ui.form.on("Purchase Receipt", {
    refresh(frm) {
        set_main_warehouse_query(frm, "set_warehouse");
        set_main_warehouse_query(frm, "rejected_warehouse");
    }
});