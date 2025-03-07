# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class ResConfigSettings(models.TransientModel):

    _inherit = ['res.config.settings']


    l10n_ec_edocument_goods_purchase_tax_id = fields.Many2one(
        related='company_id.l10n_ec_edocument_goods_purchase_tax_id',
        readonly=False)
    l10n_ec_edocument_services_purchase_tax_id = fields.Many2one(
        related='company_id.l10n_ec_edocument_services_purchase_tax_id',
        readonly=False)
    l10n_ec_edocument_goods_sale_tax_id = fields.Many2one(
        related='company_id.l10n_ec_edocument_goods_sale_tax_id',
        readonly=False)
    l10n_ec_edocument_services_sale_tax_id = fields.Many2one(
        related='company_id.l10n_ec_edocument_services_sale_tax_id',
        readonly=False)
    l10n_ec_edocument_sale_margin = fields.Float(
        related='company_id.l10n_ec_edocument_sale_margin',
        readonly=False)
    l10n_ec_edocument_state_orders = fields.Selection(
        related='company_id.l10n_ec_edocument_state_orders',
        readonly=False)
