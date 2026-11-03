# Copyright (c) 2026, Rakonex and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class StorageBin(Document):
    pass

    # def validate(self):
    #     self.validate_capacity()
        
        
    # def after_insert(self):
    #         self.update_rack_occupancy()
            
            
    # def on_update(self):
    #         self.update_rack_occupancy()
            
            
    # def after_delete(self):
    #         self.update_rack_occupancy()
            
            
    # def update_rack_occupancy(self):
        
    #     occupied = frappe.db.sql("""
	# 		SELECT COALESCE(SUM(cells_occupied), 0)
	# 		FROM `tabStorage Bin`
	# 		WHERE rack = %s
	# 	""", self.rack)[0][0]
        
    #     rack = frappe.get_doc("Rack", self.rack)
    #     rack.occupied_cells = occupied or 0
    #     rack.available_cells = (
	# 		rack.total_cells - (occupied or 0)
	# 	)
    #     if rack.available_cells <= 0:
    #         rack.status = "Full"
    #     else:
    #         rack.status = "Active"
    #     rack.save(ignore_permissions=True)

    # def validate_capacity(self):

    #     rack = frappe.get_doc("Rack", self.rack)

    #     occupied = frappe.db.sql("""
    #         SELECT COALESCE(SUM(cells_occupied), 0)
    #         FROM `tabStorage Bin`
    #         WHERE rack = %s
    #         AND name != %s
    #     """, (self.rack, self.name))[0][0] or 0

    #     available = rack.total_cells - (occupied or 0)

    #     if self.cells_occupied > available:
    #         frappe.throw(
    #             f"Only {available} cells available in Rack {self.rack}"
    #         )