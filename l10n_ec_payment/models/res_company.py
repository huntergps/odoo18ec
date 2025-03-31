# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class ResCompany(models.Model):
    _inherit = ['res.company']



    l10n_ec_payment_advance_customer_journal_id = fields.Many2one(
        comodel_name='account.journal',
        check_company=True,
        string="Diario de Anticipos de Clientes"
    )

    l10n_ec_payment_advance_vendor_journal_id = fields.Many2one(
        comodel_name='account.journal',
        check_company=True,
        string="Diario de Anticipos de Proveedores"
    )

    l10n_ec_payment_cheque_alert_inbound = fields.Integer('Para Cheques Recibidos',  default=3)
    l10n_ec_payment_cheque_alert_outbound = fields.Integer('Para Cheques Emitidos', default=3)
    
    l10n_ec_payment_cheque_email = fields.Char('Email para Cheques', )
