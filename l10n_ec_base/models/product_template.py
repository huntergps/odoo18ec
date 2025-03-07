# -*- coding: utf-8 -*-

from odoo import api, fields, models
from odoo.tools.translate import html_translate

class ProductTemplate(models.Model):
    _inherit = "product.template",

    available_in_pos = fields.Boolean(string='Disponible en POS', default=False)

    website_description = fields.Html(
        string="Description for the website",
        translate=html_translate,
        sanitize_overridable=True,
        sanitize_attributes=False, sanitize_form=False
    )
    website_description_ec = fields.Html('Descripcion del Sitio Web', sanitize_attributes=True)
    description_sale_ec = fields.Html(
        'Descripción de Ventas', translate=True, sanitize_attributes=True)
    sku = fields.Char('SKU', index=True)
    part_number = fields.Char('Nro de Parte', index=True)
    external_id = fields.Char('Id DB Externa',index=True)



class ProductProduct(models.Model):
    _inherit = "product.product"

    last_purchase_price = fields.Float(string="Ultimo Costo")
