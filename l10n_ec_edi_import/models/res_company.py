# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class ResCompany(models.Model):
    _inherit = ['res.company']


    l10n_ec_edocument_goods_purchase_tax_id = fields.Many2one(
        comodel_name='account.tax',
        check_company=True,
        string="IVA para Productos Compras"
    )
    l10n_ec_edocument_services_purchase_tax_id = fields.Many2one(
        comodel_name='account.tax',
        check_company=True,
        string="IVA para Servicios Compras"
    )

    l10n_ec_edocument_goods_sale_tax_id = fields.Many2one(
        comodel_name='account.tax',
        check_company=True,
        string="IVA para Productos Ventas"
    )
    l10n_ec_edocument_services_sale_tax_id = fields.Many2one(
        comodel_name='account.tax',
        check_company=True,
        string="IVA para Servicios Ventas"
    )

    l10n_ec_edocument_sale_margin = fields.Float(string='Margen de Ganancia Venta',
        required=True,
        default=0.0)

    l10n_ec_edocument_state_orders = fields.Selection(
        [
            ('draft', 'En borrador'),
            ('done', 'Procesar')
            ], 'Estado de Ordenes de Compras',default='done')
