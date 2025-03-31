# Part of Odoo. See LICENSE file for full copyright and licensing details.
from odoo import fields, models


class AccountMoveLine(models.Model):

    _inherit = ['account.move.line']

    cheque_id = fields.Many2one('cheque.recibido', string='Cheque Recibido')
    caja_chica_id = fields.Many2one('caja.chica', string="Caja Chica", copy=False)
