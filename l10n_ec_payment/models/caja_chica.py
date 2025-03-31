# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import datetime
from uuid import uuid4

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError




class CajaChica(models.Model):
    _name = 'caja.chica'
    _inherit = ['mail.activity.mixin', 'mail.thread']  # Agregar herencia para seguimiento y actividades
    _description = 'Caja Chica'

    @api.model
    def _get_default_journal(self):

        domain = [('type', '=', 'cash'),('caja_chica','=',True)]
        journal = self.env['account.journal'].search(domain, limit=1)
        if not journal:
            error_msg = ('No existen Diarios de Caja Chica')
            raise UserError(error_msg)
        return journal


    name = fields.Char(string='Nombre de Caja Chica', index=True, required=True)
    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', compute='_compute_currency', string="Currency")
    active = fields.Boolean(default=True)
    current_user_id = fields.Many2one('res.users', string='Current Session Responsible', compute='_compute_current_session_user')
    journal_id = fields.Many2one('account.journal', string='Diario Contable',
        domain=[('type', '=', 'sale')], default=_get_default_journal)
    partner_id = fields.Many2one('res.partner', string='Responsable', tracking=True, change_default=True)

    user_ids = fields.Many2many('res.users',string='Usuarios de la Caja')

    # reposiciones_ids = fields.One2many('caja.chica.reposicion', 'caja_chica_id',
    #     string='Reposiciones',  readonly=True)


    line_ids = fields.One2many('account.move.line', 'caja_chica_id',
        string='Detalle de Caja Chica', copy=False, readonly=True)

    debit = fields.Monetary(string='Debe', store=True,
        compute='_compute_amount')
    credit = fields.Monetary(string='Haber', store=True,
        compute='_compute_amount')

    balance = fields.Monetary(string='Saldo', store=True, readonly=True,
        compute='_compute_balance')

    limite = fields.Monetary(string='Limite')

    type = fields.Selection([
        ('normal', 'Caja Chica'),
        ('liquidity', 'Fondo a Rendir')
    ], string='Tipo', default='normal', required=True)



    # @api.depends('line_ids.debit', 'line_ids.credit','reposiciones_ids','reposiciones_ids.amount')
    @api.depends('line_ids.debit', 'line_ids.credit')
    def _compute_amount(self):
        balance =0.0
        for rec in self:
            others_lines = rec.line_ids.filtered(lambda line: line.parent_state in ('posted'))
            debit = sum(others_lines.mapped('debit')) or 0.0
            credit = sum(others_lines.mapped('credit')) or 0.0
            rec.debit = debit
            rec.credit = credit
            rec.balance = debit-credit


    @api.depends('debit', 'credit')
    def _compute_balance(self):
        for line in self:
            line.balance = line.debit - line.credit


    @api.depends('journal_id.currency_id', 'journal_id.company_id.currency_id', 'company_id', 'company_id.currency_id')
    def _compute_currency(self):
        for payec_config in self:
            payec_config.currency_id = payec_config.company_id.currency_id.id


    def name_get(self):
        result = []
        for config in self:
            result.append((config.id, config.name))
        return result
