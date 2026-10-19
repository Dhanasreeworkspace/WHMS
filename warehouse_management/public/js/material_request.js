frappe.ui.form.on("Material Request", {
    refresh: function(frm) {
        if (frm.doc.docstatus === 0) {
            update_available_stock(frm);
        }

        set_stock_at_source_tooltip(frm);

        // Assign Picker button for submitted Material Requests
        if (frm.doc.docstatus === 1 && frm.doc.workflow_state === "Approved") {
            frm.add_custom_button(__("Assign Picker"), function () {
                open_item_selection_dialog(frm);
            });
        }

        setTimeout(() => {
            frm.page.wrapper
                .find('.btn:contains("Approve"), .dropdown-item:contains("Approve")')
                .off('click')
                .on('click', function(e) {
                    e.preventDefault();
                    e.stopImmediatePropagation();
                    handle_approve_click(frm);
                });
        }, 300);
    },

    set_from_warehouse(frm) {
        if (frm.doc.docstatus === 0) {
            update_available_stock(frm);
        }
    },
});


frappe.ui.form.on("Material Request Item", {
    item_code(frm, cdt, cdn) {
        if (frm.doc.docstatus === 0) {
            update_available_stock(frm, cdt, cdn);
        }
    },
});

// --------------------------------------------------
// STOCK AVAILABILITY
// --------------------------------------------------

function set_stock_at_source_tooltip(frm) {
    const tooltip = frm.doc.docstatus === 0
        ? __("Stock at Source (Currently Available)")
        : __("Stock at Source (At Time of Approval)");

    setTimeout(() => {
        if (frm.fields_dict.items) {
            frm.fields_dict.items.grid.wrapper
                .find('[data-fieldname="stock_available_at_source"]')
                .attr("title", tooltip);
        }
    }, 100);
}


function update_available_stock(frm) {
    const warehouse = frm.doc.set_from_warehouse;

    if (!warehouse) {
        (frm.doc.items || []).forEach((row) => {
            row.stock_available_at_source = 0;
        });
        return;
    }

    const item_codes = [...new Set(
        (frm.doc.items || [])
            .map(row => row.item_code)
            .filter(Boolean)
    )];

    if (!item_codes.length) {
        return;
    }

    frappe.call({
        method: "warehouse_management.events.stock_availability.get_available_qty_for_items",
        args: {
            item_codes: item_codes,
            warehouse: warehouse,
        },
        callback(r) {
            const stock_map = r.message || {};

            (frm.doc.items || []).forEach((row) => {
                row.stock_available_at_source = stock_map[row.item_code] || 0;
            });

            set_stock_at_source_tooltip(frm);
        },
    });
}

// --------------------------------------------------
// ASSIGN PICKER
// --------------------------------------------------

function open_item_selection_dialog(frm) {
    frappe.call({
        method: "warehouse_management.events.material_request.get_picker_assignment_data",
        args: {material_request: frm.doc.name},
        freeze: true,
        freeze_message: __("Loading items..."),

        callback(r) {
            if (!r.message) {
                return;
            }

            const items = r.message.items || [];
            const selected_items = new Set();

            const dialog = new frappe.ui.Dialog({
                title: __("Assign Picker"),
                size: "large",

                fields: [
                    {
                        fieldname: "item_search",
                        fieldtype: "Data",
                        placeholder: __("Search by Item Code or Item Name"),
                    },
                    {
                        fieldname: "items_html",
                        fieldtype: "HTML",
                    },
                ],

                primary_action_label: __("Assign"),

                primary_action() {
                    if (!selected_items.size) {
                        frappe.msgprint(
                            __("Please select at least one item.")
                        );
                        return;
                    }

                    const selected_rows = items.filter(item =>
                        selected_items.has(item.name)
                    );

                    dialog.hide();

                    open_picker_selection_dialog(
                        frm,
                        selected_rows
                    );
                },
            });

            const escape_html = frappe.utils.escape_html;

            let rows_html = "";

            items.forEach(item => {
                rows_html += `
                    <tr
                        class="picker-item-row"
                        data-item-code="${escape_html(item.item_code || "")}"
                        data-item-name="${escape_html(item.item_name || "")}"
                    >
                        <td class="text-center">
                            <input
                                type="checkbox"
                                class="picker-item-checkbox"
                                value="${escape_html(item.name)}"
                            >
                        </td>

                        <td>
                            ${escape_html(item.item_code || "")}
                        </td>

                        <td>
                            ${escape_html(item.item_name || "")}
                        </td>

                        <td>
                            ${escape_html(String(item.qty ?? 0))}
                        </td>

                        <td>
                            ${escape_html(item.assigned_picker || "")}
                        </td>
                    </tr>
                `;
            });

            const html = `
                <div class="picker-items-container">

                    <div style="
                        max-height: 450px;
                        overflow-y: auto;
                        border: 1px solid var(--border-color);
                        border-radius: 4px;
                    ">
                        <table class="table table-bordered table-hover"
                               style="margin-bottom: 0;">

                            <thead style="
                                position: sticky;
                                top: 0;
                                background: var(--bg-color);
                                z-index: 1;
                            ">
                                <tr>
                                    <th style="width: 40px;">
                                        <input
                                            type="checkbox"
                                            class="select-all-picker-items"
                                            aria-label="Select all visible items"
                                        >
                                    </th>

                                    <th>${__("Item Code")}</th>
                                    <th>${__("Item Name")}</th>
                                    <th>${__("Qty")}</th>
                                    <th>${__("Current Picker")}</th>
                                </tr>
                            </thead>

                            <tbody>
                                ${rows_html}
                            </tbody>

                        </table>
                    </div>

                    <div class="selected-items-count"
                         style="margin-top: 12px;">
                        0 ${__("item(s) selected")}
                    </div>

                </div>
            `;

            const wrapper = dialog.fields_dict.items_html.$wrapper;

            wrapper.html(html);

            function update_selected_count() {
                wrapper.find(".selected-items-count").text(
                    `${selected_items.size} ${__("item(s) selected")}`
                );

                const visible_checkboxes = wrapper
                    .find(".picker-item-checkbox")
                    .filter(function () {
                        return $(this).closest("tr").is(":visible");
                    });

                const checked_count = visible_checkboxes.filter(":checked").length;

                wrapper.find(".select-all-picker-items").prop(
                    "checked",
                    visible_checkboxes.length > 0 &&
                    checked_count === visible_checkboxes.length
                );
            }

            // Individual checkbox selection.
            wrapper.on(
                "change",
                ".picker-item-checkbox",
                function () {
                    const item_name = $(this).val();

                    if (this.checked) {
                        selected_items.add(item_name);
                    } else {
                        selected_items.delete(item_name);
                    }

                    update_selected_count();
                }
            );

            // Select or deselect all currently visible items.
            wrapper.on(
                "change",
                ".select-all-picker-items",
                function () {
                    const checked = this.checked;

                    wrapper.find(".picker-item-checkbox").each(function () {
                        if (!$(this).closest("tr").is(":visible")) {
                            return;
                        }

                        const item_name = $(this).val();

                        $(this).prop("checked", checked);

                        if (checked) {
                            selected_items.add(item_name);
                        } else {
                            selected_items.delete(item_name);
                        }
                    });

                    update_selected_count();
                }
            );

            // Search by Item Code or Item Name.
            dialog.fields_dict.item_search.$input.on(
                "input",
                function () {
                    const search_text = (
                        $(this).val() || ""
                    ).toLowerCase().trim();

                    wrapper.find(".picker-item-row").each(function () {
                        const item_code = String(
                            $(this).attr("data-item-code") || ""
                        ).toLowerCase();

                        const item_name = String(
                            $(this).attr("data-item-name") || ""
                        ).toLowerCase();

                        const matches =
                            item_code.includes(search_text) ||
                            item_name.includes(search_text);

                        $(this).toggle(matches);
                    });

                    update_selected_count();
                }
            );

            dialog.show();
        },
    });
}


function open_picker_selection_dialog(frm, selected_rows) {
    const picker_dialog = new frappe.ui.Dialog({
        title: __("Assign Picker"),

        fields: [
            {
                fieldname: "picker",
                label: __("Select Picker"),
                fieldtype: "Link",
                options: "User",
                reqd: 1,

                get_query() {
                    return {
                        query: "warehouse_management.events.material_request.get_picker_users",
                    };
                },
            },
        ],

        primary_action_label: __("Assign"),

        primary_action(values) {
            if (!values.picker) {
                frappe.msgprint(
                    __("Please select a picker.")
                );
                return;
            }

            frappe.call({
                method: "warehouse_management.events.material_request.assign_picker_to_items",

                args: {
                    material_request: frm.doc.name,
                    picker: values.picker,
                    items: selected_rows.map(item => item.name),
                },

                freeze: true,
                freeze_message: __("Assigning picker..."),

                callback(r) {
                    if (r.message && r.message.success) {
                        picker_dialog.hide();

                        frappe.show_alert({
                            message: __(
                                "Picker assigned to {0} item(s).",
                                [r.message.assigned_count]
                            ),
                            indicator: "green",
                        });

                        frm.reload_doc();
                    }
                },
            });
        },
    });

    picker_dialog.show();
}

// --------------------------------------------------
// MATERIAL REQUEST APPROVAL
// --------------------------------------------------

function handle_approve_click(frm) {
    frappe.call({
        method: "warehouse_management.events.material_request.get_conflicting_pending_mrs",
        args: { material_request: frm.doc.name },
        freeze: true,
        freeze_message: __("Checking for conflicts..."),
        callback: function(r) {
            let conflicts = r.message || [];

            if (!conflicts.length) {
                run_workflow_action(frm, 'Approve');
                return;
            }

            show_conflict_dialog(frm, conflicts);
        }
    });
}


function show_conflict_dialog(frm, conflicts) {
    let rows = conflicts.map(c => {
        let mr_link = frappe.utils.get_form_link
            ? frappe.utils.get_form_link("Material Request", c.mr_name)
            : `/app/material-request/${encodeURIComponent(c.mr_name)}`;

        return `
            <tr>
                <td><a href="${mr_link}" target="_blank">${frappe.utils.escape_html(c.mr_name)}</a></td>
                <td>${frappe.utils.escape_html(c.target_warehouse || '')}</td>
                <td>${frappe.utils.escape_html(c.item_code)}</td>
                <td>${frappe.utils.escape_html(c.item_name || '')}</td>
                <td style="text-align:right">${c.qty}</td>
            </tr>
        `;
    }).join('');

    let table_html = `
        <div style="max-height: 400px; overflow-y: auto;">
            <table class="table table-bordered">
                <thead>
                    <tr>
                        <th>Material Request</th>
                        <th>Target Warehouse</th>
                        <th>Item Code</th>
                        <th>Item Name</th>
                        <th style="text-align:right">Qty</th>
                    </tr>
                </thead>

                <tbody>${rows}</tbody>
            </table>
        </div>
    `;

    let d = new frappe.ui.Dialog({
        title: __('Conflicting Pending Material Requests'),
        size: 'large',
        fields: [
            { fieldtype: 'HTML', fieldname: 'conflict_table', options: table_html }
        ],
        primary_action_label: __('Approve Anyway'),
        primary_action: () => {
            d.hide();
            run_workflow_action(frm, 'Approve');
        },
        secondary_action_label: __('Cancel'),
        secondary_action: () => {
            d.hide();
        }
    });

    d.show();
}


function run_workflow_action(frm, action) {
    frappe.dom.freeze(__("Updating..."));
    frappe.xcall('frappe.model.workflow.apply_workflow', { doc: frm.doc, action: action })
        .then((doc) => {
            frappe.model.sync(doc);
            frm.refresh();
        })
        .finally(() => {
            frappe.dom.unfreeze();
        });
}