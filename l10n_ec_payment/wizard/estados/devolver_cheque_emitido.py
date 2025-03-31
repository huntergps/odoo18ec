# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class ReturnCheque(models.TransientModel):
    _name = "return.cheque"
    _description = "return.cheque"

    date_present = fields.Date(string='Cheque Present Date', default=fields.Date.context_today, required=True)
    date_return = fields.Date(string='Fecha de devolución', default=fields.Date.context_today, required=True)
    amount = fields.Float('Cargos Bancarios', required=True)
    reason_id = fields.Many2one('return.reason', string='Razon', required=True)
    comment_required = fields.Boolean(string="Comentarios requeridos ?")
    comment = fields.Text(string="Comentarios")

    @api.onchange('reason_id')
    def _onchange_reason(self):
        if self.reason_id:
            self.comment_required = self.reason_id.comment_required


    def return_cheque(self):
        cheque_obj = self.env['cheque.emitido'].browse(self.env.context.get('active_id'))
        cheque_config = self.env['res.config.settings'].search([], order='id desc', limit=1)
        print(cheque_config)
        if not cheque_config.devolucion_product_id:
            raise UserError('No se han establecido el producto para devolución del Cheque')
        devolucion_product_id = cheque_config.devolucion_product_id.id
        if not cheque_config.comision_product_id:
            raise UserError('No se han establecido el producto para la Comisión Bancaria de devolución del Cheque')
        comision_product_id = cheque_config.comision_product_id.id
        descripcion = 'Devolución de Cheque Emitido '+cheque_obj.cheque_no
        valsDeuda = {
                    'name': descripcion,
                    'product_id': devolucion_product_id,
                    'product_uom_id': self.env.ref('uom.product_uom_unit').id,
                    'quantity': 1,
                    'price_unit': cheque_obj.amount,
                    'account_id':cheque_obj.bank_account_id.id,
                    'tax_ids': [],
                    }
        # journal_id = self._get_default_journal_id()
        print(cheque_obj.bank_account_id.name)
        vals_asiento = {
            'currency_id': cheque_obj.currency_id.id,
            'invoice_origin': cheque_obj.name,
            'invoice_payment_term_id':self.env.ref('account.account_payment_term_immediate').id,
        }
        vals_asiento['name'] = descripcion
        vals_asiento['partner_id'] = cheque_obj.partner_id.id
        vals_asiento['type'] = 'in_receipt'
        vals_asiento['ref'] = descripcion
        vals_asiento['invoice_line_ids'] = []
        vals_asiento['invoice_date'] = str(self.date_return)
        vals_asiento['invoice_date_due'] = str(self.date_return)
        vals_asiento['invoice_line_ids'].append((0, 0, valsDeuda))
        table_obj = self.env['account.move']
        print(vals_asiento)

        account_move = table_obj.create(vals_asiento)
        if cheque_obj.comment:
            comment = cheque_obj.comment + "\n" + self.reason_id.name
        else:
            comment = self.reason_id.name
        if self.comment:
            comment = comment + "\n" + self.comment
        cheque_obj.write({'state': 'returned', 'return_date': self.date_return, 'comment': comment,'account_move_ids': [(4, account_move.id)],})


    def _get_default_journal_id(self):
        journal_obj = self.env['cheque.emitido']
        print(journal_obj)
        journal_id=None
        journal_ids = journal_obj.search([('type', '=', 'in_receipt')])
        print(journal_ids)
        journal_id = journal_ids and journal_ids[0] or False
        return journal_id

    def return_cheque1(self):
        cheque_obj = self.env['cheque.emitido'].browse(self.env.context.get('active_id'))
        raise UserError('Revisar los diarios para anular los asientos')

        cheque_config = self.env['cheque.config.settings'].search([], order='id desc', limit=1)
        if not cheque_config.comprobante_emitido_journal_id:
            raise UserError(_('Set Cheque Payment Journal under Settings !!!'))
        journal_id = cheque_config.comprobante_emitido_journal_id.id
        line_ids = []
        if self.amount and self.amount > 0:
            line_ids = [(0, 0,
             {'journal_id': journal_id, 'account_id': cheque_obj.bank_account_id.account_id.id, 'name': '/',
              'amount_currency': 0.0, 'credit': self.amount}),
            (0, 0, {'journal_id': journal_id, 'account_id': cheque_obj.bank_account_id.return_account_id.id,
                    'name': 'Bank Charges', 'partner_id': cheque_obj.partner_id.id, 'amount_currency': 0.0, 'debit': self.amount}),]
        line_ids.extend([
            (0, 0,
             {'journal_id': journal_id, 'account_id': cheque_obj.partner_account_id.id, 'name': '/',
              'amount_currency': 0.0, 'credit': cheque_obj.amount}),
            (0, 0, {'journal_id': journal_id, 'account_id': cheque_obj.bank_account_id.account_id.id,
                    'name': cheque_obj.name, 'amount_currency': 0.0, 'debit': cheque_obj.amount}),
            (0, 0,
             {'journal_id': journal_id, 'account_id': cheque_obj.bank_account_id.account_id.id, 'name': '/',
              'amount_currency': 0.0, 'credit': cheque_obj.amount}),
            (0, 0, {'journal_id': journal_id, 'account_id': cheque_obj.bank_account_id.pdc_account_id.id,
                    'name': cheque_obj.name, 'amount_currency': 0.0, 'debit': cheque_obj.amount})
        ])
        vals = {
            'journal_id': journal_id,
            'ref': cheque_obj.name,
            'date': self.date_return,
            'line_ids': line_ids,
        }
        account_move = self.env['account.move'].create(vals)
        account_move.post()
        if cheque_obj.comment:
            comment = cheque_obj.comment + "\n" + self.reason_id.name
        else:
            comment = self.reason_id.name
        if self.comment:
            comment = comment + "\n" + self.comment
        cheque_obj.write({'state': 'returned', 'return_date': self.date_return, 'comment': comment,'account_move_ids': [(4, account_move.id)],})
