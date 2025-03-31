# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = ['res.config.settings']


    l10n_ec_payment_advance_customer_journal_id = fields.Many2one(
        related='company_id.l10n_ec_payment_advance_customer_journal_id',
        readonly=False,
        string="Diario de Anticipos de Clientes"
    )

    l10n_ec_payment_advance_vendor_journal_id = fields.Many2one(
        related='company_id.l10n_ec_payment_advance_vendor_journal_id',
        readonly=False,
        string="Diario de Anticipos de Proveedores"
    )

    l10n_ec_payment_cheque_alert_inbound = fields.Integer(
        related='company_id.l10n_ec_payment_cheque_alert_inbound',
        readonly=False,
        string="Plazo para Cheques Recibidos"
    )
    l10n_ec_payment_cheque_alert_outbound = fields.Integer(
        related='company_id.l10n_ec_payment_cheque_alert_outbound',
        readonly=False,
        string="Plazo para Cheques Emitidos"
    )    
    
    l10n_ec_payment_cheque_email = fields.Char(
        related='company_id.l10n_ec_payment_cheque_email',
        readonly=False,
        string="Email para Cheques Emitidos"
    )    
