# Part of Odoo. See LICENSE file for full copyright and licensing details.

from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import float_round, format_list

from odoo.addons.base.models.res_partner import WARNING_HELP, WARNING_MESSAGE


class ProductTemplate(models.Model):
    _inherit = ['product.template']
    _check_company_auto = True

    edocument_product_ids = fields.One2many('edocument.product.supplier', 'product_tmpl_id', 'Homologacion', depends_context=('company',))
    edocument_product_variant_ids = fields.One2many('edocument.product.supplier', 'product_tmpl_id')
