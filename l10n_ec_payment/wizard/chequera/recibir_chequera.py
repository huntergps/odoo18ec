# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from datetime import datetime


class RecibirChequera(models.TransientModel):
    _name = "recibir.chequera"
    _description = "Recibir Chequera"

    @api.model
    def default_get(self, default_fields):
        rec = super(RecibirChequera, self).default_get(default_fields)
        jrnl_filters  = ['bank']
        domain_on_types = [('type', 'in', list(jrnl_filters)),('tiene_chequera','=',True)]
        bank_account_id =self.env['account.journal'].search(domain_on_types, limit=1)
        rec.update({
            'bank_account_id': bank_account_id.id or False
        })
        return rec



    bank_account_id = fields.Many2one('account.journal', string="Cuenta Bancaria")

    cheque_from = fields.Integer(string='Desde', required=True)
    cheque_to = fields.Integer(string='Hasta', required=True)

    # @api.onchange('cheque_from', 'cheque_to')
    # def _onchange_cheque_no(self):
    #     if self.cheque_from > self.cheque_to:
    #         raise UserError(_('Reset Cheque Number From and To properly.'))

    def receive_cheque(self):
        if self.cheque_from > self.cheque_to:
            raise UserError(_('Reset Cheque Number From and To properly.'))
        bank_account_id = self.bank_account_id
        cheque_from = self.cheque_from
        cheque_to = self.cheque_to
        cheque_obj = self.env['cheque.emitido']
        for x in range(cheque_from, cheque_to+1):
            name = '[' + str(x) + '] ' + bank_account_id.name
            similar_cheques = cheque_obj.search([('name', '=', name)])
            if similar_cheques:
                raise UserError('Verifique que la secuencia de cheques no hayan sido generadas')
        for x in range(cheque_from, cheque_to+1):
            name = '[' + str(x) + '] ' + bank_account_id.name
            vals = {
                'name': name,
                'cheque_no': x,
                'bank_account_id': bank_account_id.id,
                'state': 'new'
                    }
            cheque_obj.create(vals)
        return {
            'name': 'Chequera',
            'view_mode': 'kanban,tree,form',
            'res_model': 'cheque.emitido',
            'context': 'None'
        }

    def action_clear(self):
        return {
            'name': 'Recibir Chequera',
            'view_mode': 'form',
            'res_model': 'recibir.chequera',
            'target': 'new',
            'context': 'None'
        }
