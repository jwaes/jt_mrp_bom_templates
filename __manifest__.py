# -*- coding: utf-8 -*-
{
    'name': "jt_mrp_bom_templates",

    'summary': "Mrp BOM templates",

    'description': "",

    'author': "jaco tech",
    'website': "https://jaco.tech",
    "license": "AGPL-3",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/15.0/odoo/addons/base/data/ir_module_category_data.xml
    # for the full list
    'category': 'Uncategorized',
    'version': '0.9',

    # any module necessary for this one to work correctly
    'depends': ['base', 'mail' ,'mrp'],

    # always loaded
    'data': [
        'data/bom_template_data.xml',
        'security/ir.model.access.csv',
        'views/mail_templates.xml',
        'views/mrp_bom_views.xml',
        'views/product_template.xml',
    ],


}
