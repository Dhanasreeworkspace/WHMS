frappe.ui.form.on("Consignment Sales Order", {
    setup(frm) {
        frm.set_query("warehouse", function () {
            return {
                filters: [
                    ["Warehouse", "external", "=", 1]
                ]
            };
        });
    }
});