frappe.ui.form.on("Consignment Sales Order", {
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
    },
        // Update stock when Source Warehouse changes or form loads
    refresh(frm) {
        if (frm.doc.docstatus === 0) {
            update_stock_at_source(frm);
        }
    },

    source_warehouse(frm) {
        if (frm.doc.docstatus === 0) {
            update_stock_at_source(frm);
        }
    }
});
// update Amount when Quantity or Rate Changes
frappe.ui.form.on("Consignment Sales Order Item", {
    item_code(frm, cdt, cdn) {
        if (!frm.doc.docstatus) update_stock_at_source(frm, cdt, cdn);
    },
    quantity(frm, cdt, cdn) {
        calculate_amount(cdt, cdn);
    },

    rate(frm, cdt, cdn) {
        calculate_amount(cdt, cdn);
    }
});
function calculate_amount(cdt, cdn) {
    let row = locals[cdt][cdn];
    let amount = (row.quantity || 0) * (row.rate || 0);

    frappe.model.set_value(cdt, cdn, "amount", amount);
}

const stock_request_tokens = {};

function update_stock_at_source(frm, cdt, cdn) {
    const warehouse = frm.doc.source_warehouse;
    const rows = cdt ? [locals[cdt]?.[cdn]].filter(Boolean) : frm.doc.items || [];

    const pending = rows.map(row => ({
        ...row,
        token: stock_request_tokens[row.name] = (stock_request_tokens[row.name] || 0) + 1
    }));

    pending.filter(row => !warehouse || !row.item_code).forEach(row =>
        frappe.model.set_value(row.doctype, row.name, "stock_at_source", 0)
    );

    if (!warehouse) return;

    const item_codes = [...new Set(pending.map(row => row.item_code).filter(Boolean))];
    if (!item_codes.length) return;

    frappe.call({
        method: "warehouse_management.events.stock_availability.get_available_qty_for_items",
        args: { item_codes, warehouse },
        callback(r) {
            if (r.exc || frm.doc.source_warehouse !== warehouse) return;

            pending.forEach(row => {
                const current = locals[row.doctype]?.[row.name];
                if (current?.item_code === row.item_code &&
                    stock_request_tokens[row.name] === row.token) {
                    frappe.model.set_value(row.doctype, row.name, "stock_at_source",
                        r.message?.[row.item_code] || 0);
                }
            });
        }
    });
}