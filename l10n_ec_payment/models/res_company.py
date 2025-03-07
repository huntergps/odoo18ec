# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class ResCompany(models.Model):
    _inherit = ['res.company']


    l10n_ec_payment_advance_customer_id = fields.Many2one(
        comodel_name='account.account',
        check_company=True,
        string="Cuenta de Anticipos de Clientes"
    )
    
    l10n_ec_payment_advance_vendor_id = fields.Many2one(
        comodel_name='account.account',
        check_company=True,
        string="Cuenta de Anticipos de Proveedores"
    )
