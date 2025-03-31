# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from datetime import datetime


class IssueChequeWizard(models.TransientModel):
    _name = "issue.cheque.wizard"
    _description = "issue.cheque.wizard"

    receiver_name = fields.Char(string='Nombre de quien recibe', required=True)
    designation = fields.Char(string='Cargo')
    phone = fields.Char(string='Fono de Contacto.', required=True)
    cheque_date_print = fields.Date(string='Fecha de Entrega', default=fields.Date.context_today, required=True)


    def issue_cheque(self):
        cheque_obj = self.env['cheque.emitido'].browse(self.env.context.get('active_id'))
        cheque_obj.write({'state': 'issued',
                          'receiver_name': self.receiver_name,
                          'designation': self.designation,
                          'phone': self.phone,
                          'cheque_date_issue': self.cheque_date_print
                          })
