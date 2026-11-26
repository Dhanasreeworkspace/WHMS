frappe.ui.form.on("Purchase Order", {
    refresh(frm) {
        set_main_warehouse_query(frm, "set_warehouse");
    }
});