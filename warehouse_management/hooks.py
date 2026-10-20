app_name = "warehouse_management"
app_title = "Warehouse Management"
app_publisher = "Rakonex"
app_description = "Warehouse Management System"
app_email = "dev3@rakonex.com"
app_license = "mit"

# Fixtures
# --------

fixtures = [
	{
		"doctype": "Custom Field",
		"filters": [
			["dt", "in", ["Purchase Receipt Item", "Stock Entry Detail", "Material Request Item"]],
			["fieldname", "in", [
				"rack", "bin", "date_of_assignment", "expiry_date", "stock_available_at_source", "assigned_picker"
			]]
		]
	},
	{
		"doctype": "Workflow",
		"filters": [
			["name", "in", ["Material Request Approval"]]
		]
	},
	{
		"doctype": "Workflow State",
		"filters": [
			["workflow_state_name", "in", ["Draft", "Submitted", "Pending", "Cancelled", "Picked", "Packed", "In Transit", "Completed"]]
		]
	},
	{
		"doctype": "Workflow Action Master",
		"filters": [
			["workflow_action_name", "in", ["Cancel", "Submit"]]
		]
	},
	{
		"doctype": "Property Setter",
		"filters": [
			["name", "in", [
				"Material Request-set_from_warehouse-mandatory_depends_on",
				"Warehouse-warehouse_type-reqd",
				"Material Request Item-warehouse-in_list_view",
				"Material Request Item-schedule_date-in_list_view"
			]]
		]
	},
	{
		"doctype": "Warehouse Type",
		"filters": [
			["name", "in", ["Bay", "Storage", "Hold", "Outward"]]
		]
	},
]
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "warehouse_management",
# 		"logo": "/assets/warehouse_management/logo.png",
# 		"title": "Warehouse Management",
# 		"route": "/warehouse_management",
# 		"has_permission": "warehouse_management.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/warehouse_management/css/warehouse_management.css"
app_include_js = [
	"/assets/warehouse_management/js/stock_availability.js",
]

# include js, css files in header of web template
# web_include_css = "/assets/warehouse_management/css/warehouse_management.css"
# web_include_js = "/assets/warehouse_management/js/warehouse_management.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "warehouse_management/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
doctype_js = {
	"Employee" : "public/js/employee.js",
	"Warehouse" : "public/js/warehouse.js",
	"Material Request" : "public/js/material_request.js",
    "Pick List": "public/js/pick_list.js",
}
doctype_list_js = {
	"Material Request": "public/js/material_request_list.js",
}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "warehouse_management/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "warehouse_management.utils.jinja_methods",
# 	"filters": "warehouse_management.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "warehouse_management.install.before_install"
# after_install = "warehouse_management.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "warehouse_management.uninstall.before_uninstall"
# after_uninstall = "warehouse_management.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "warehouse_management.utils.before_app_install"
# after_app_install = "warehouse_management.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "warehouse_management.utils.before_app_uninstall"
# after_app_uninstall = "warehouse_management.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "warehouse_management.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

permission_query_conditions = {
	"Material Request": "warehouse_management.events.material_request.get_permission_query_conditions"
}
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"Purchase Receipt": {
		"on_submit": "warehouse_management.warehouse_management.doctype.bin_assignment.bin_assignment.create_bin_assignments_on_purchase_receipt_submit"
	},
	"Material Request": {
		"validate": "warehouse_management.events.material_request.validate_warehouse_manager",
		"before_save": "warehouse_management.events.material_request.update_stock_available_at_source",
		"on_update": "warehouse_management.events.material_request.notify_warehouse_manager",
	},
	"Pick List": {
		"validate": "warehouse_management.events.pick_list.validate_material_requests",
		"on_submit": "warehouse_management.events.pick_list.update_material_requests_as_picked",
		"on_cancel": [
			"warehouse_management.events.pick_list.revert_material_requests_to_approved",
			"warehouse_management.events.pick_list.delete_bin_assignments_on_pick_list_cancel",
		]
	},
	"Stock Entry": {
		"on_submit": [
			"warehouse_management.events.stock_entry.update_material_request_workflow",
			"warehouse_management.events.stock_entry.create_bin_assignments_on_stock_entry_submit",
		],
		"on_cancel": [
			"warehouse_management.events.stock_entry.revert_material_request_workflow",
			"warehouse_management.events.stock_entry.delete_bin_assignments_on_stock_entry_cancel",
		],
	},
	"Warehouse": {
		"validate": "warehouse_management.events.warehouse.validate_warehouse_type"
	}
}

# Scheduled Tasks
# ---------------

scheduler_events = {
	"daily": [
		"warehouse_management.tasks.check_critical_stock"
	],
}

# Testing
# -------

# before_tests = "warehouse_management.install.before_tests"

# Overriding Methods
# ------------------------------

override_whitelisted_methods = {
	"frappe.desk.link_preview.get_preview_data": "warehouse_management.overrides.link_preview.get_preview_data"
}

# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "warehouse_management.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["warehouse_management.utils.before_request"]
# after_request = ["warehouse_management.utils.after_request"]

# Job Events
# ----------
# before_job = ["warehouse_management.utils.before_job"]
# after_job = ["warehouse_management.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"warehouse_management.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

