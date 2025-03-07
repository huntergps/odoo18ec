# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class ResConfigSettings(models.TransientModel):

    _inherit = ['res.config.settings']

    l10n_ec_payment_advance_customer_id = fields.Many2one(
        related='company_id.l10n_ec_payment_advance_customer_id',
        readonly=False)

    l10n_ec_payment_advance_vendor_id = fields.Many2one(
        related='company_id.l10n_ec_payment_advance_vendor_id',
        readonly=False)
