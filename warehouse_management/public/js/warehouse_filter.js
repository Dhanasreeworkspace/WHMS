function set_main_warehouse_query(frm, fieldname) {
    const field = frm.fields_dict[fieldname];

    field.get_query = function () {
        return {
            filters: [
                ["Warehouse", "is_group", "=", 0],
                ["Warehouse", "is_sub_warehouse", "=", 0],
                ["Warehouse", "disabled", "=", 0]
            ]
        };
    };
}