# Copyright (c) 2026, Rakonex and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt



class StorageBin(Document):
    def autoname(self):
        self.name = f"{self.rack} - {self.bin_id}"


    def validate(self):
        total_qty = sum(item.quantity or 0 for item in self.items)

        self.total_quantity = total_qty

        if total_qty > 0:
            self.status = "Occupied"
        else:
            self.status = "Empty"
