frappe.ui.form.on("Pick List", {
    refresh(frm) {
        // Filter custom Source and Destination Warehouse fields
        set_main_warehouse_query(frm, "source_warehouse");
        set_main_warehouse_query(frm, "destination_warehouse");

        if (frm.doc.docstatus !== 1) {
            return;
        }

        if (frm.doc.purpose !== "Material Transfer") {
            return;
        }

        if (frm.doc.status === "Completed") {
            return;
        }

        frm.add_custom_button(
            __("Create Packing List"),
            () => {
                frappe.route_options = {
                    pick_list: frm.doc.name
                };

                frappe.set_route("Form", "Packing List", "new");
            },
            __("Create")
        );
    }
});