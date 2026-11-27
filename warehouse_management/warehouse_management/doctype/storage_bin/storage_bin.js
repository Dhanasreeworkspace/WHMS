// Copyright (c) 2026, Rakonex and contributors
// For license information, please see license.txt

frappe.ui.form.on("Storage Bin", {
    refresh(frm) {
        frm.trigger("warehouse");
    },

    async warehouse(frm) {
        if (!frm.doc.warehouse) {
            frm.toggle_display("is_default", false);
            return;
        }

        const r = await frappe.db.get_value(
            "Warehouse", frm.doc.warehouse, "warehouse_type"
        );

        frm.toggle_display("is_default", r.message?.warehouse_type === "Bay");
    }
});