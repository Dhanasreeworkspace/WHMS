frappe.ui.form.on("Consignment Order", {
    setup(frm) {
        frm.set_query("customer", function () {         // Filter only Consignment group customers
            return {
                filters: [
                    ["Customer", "customer_group", "=", "Consignment"]
                ]
            };
        });
        frm.set_query("warehouse", function () {      //Filter only external warehouses
            return {
                filters: [
                    ["Warehouse", "external", "=", 1]
                ]
            };
        });
        frm.set_query("source_warehouse", function () {
            return {
                filters: [
                    ["Warehouse", "external", "=", 0],
                    ["Warehouse", "warehouse_type", "=", "Storage"]
                ]
            };
        });
    },
    async customer(frm) {                              //// Automatically set warehouse from selected customer
        if (!frm.doc.customer) {
            await frm.set_value("warehouse", "");
            return;
        }

        const { message } = await frappe.db.get_value(
            "Customer",
            frm.doc.customer,
            "consignment_warehouse"
        );

        const warehouse = message?.consignment_warehouse || "";

        await frm.set_value("warehouse", warehouse);
    }
});