# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from datetime import datetime


class CancelCheque(models.TransientModel):
    _name = "cancel.cheque"
    _description = "cancel.cheque"

    comment = fields.Text(string="Comentarios", required=True)
    date_cancel = fields.Date(string='Fecha de Cancelación', default=fields.Date.context_today, required=True)


    def cancel_cheque(self):
        cheque_obj = self.env['cheque.emitido'].browse(self.env.context.get('active_id'))
        if cheque_obj.state in ('used','new'):
            cheque_obj.write({'comment': self.comment, 'state': 'cancelled'})
        else:
            raise UserError('Revisar los diarios para anular los asientos')
            cheque_config = self.env['cheque.config.settings'].search([], order='id desc', limit=1)
            if not cheque_config.comprobante_emitido_journal_id:
                raise UserError(_('Set Cheque Payment Journal under Settings !!!'))
            journal_id = cheque_config.comprobante_emitido_journal_id.id
            line_ids = [
                (0, 0,
                 {'journal_id': journal_id, 'account_id': cheque_obj.bank_account_id.pdc_account_id.id,
                  'name': cheque_obj.name,
                  'amount_currency': 0.0, 'debit': cheque_obj.amount}),
                (0, 0, {'journal_id': journal_id, 'account_id': cheque_obj.partner_account_id.id, 'name': '/',
                        'amount_currency': 0.0, 'credit': cheque_obj.amount, 'partner_id': cheque_obj.partner_id.id})
            ]

            vals = {
                'journal_id': journal_id,
                'ref': cheque_obj.name,
                'date': self.date_cancel,
                'line_ids': line_ids,
            }
            account_move = self.env['account.move'].create(vals)
            account_move.post()
            cheque_obj.write({'comment': self.comment, 'cancel_date': self.date_cancel, 'state': 'cancelled','account_move_ids': [(4, account_move.id)],})
