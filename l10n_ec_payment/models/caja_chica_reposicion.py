# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import datetime
from uuid import uuid4

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError

import json


class CajaChicaReposicion(models.Model):
    _name = 'caja.chica.reposicion'
    _description = 'Reposicion de Caja Chica'
    _inherit = ['mail.thread', 'mail.activity.mixin']


    def name_get(self):
        res = []
        for r in self:
            _name = ''
            if r.balance!=0:
                _name += '[$%.2f]'%r.balance
            res.append((r.id, ('%s %s')%(r.name, _name,)))
        return res


    def button_cancel_and_delete(self):
        for rec in self:
            if rec.state!='draft':
                rec.write({'state':'draft'})
            rec.unlink()
        return True

    def unlink(self):
        if self.filtered(lambda reposicion: reposicion.state != 'draft'):
            raise UserError("Solo se pueden borrar los registros en estado Borrador")
        return super(CajaChicaReposicion, self).unlink()

    @api.depends('journal_id.currency_id', 'journal_id.company_id.currency_id', 'company_id', 'company_id.currency_id')
    def _compute_currency(self):
        for payec_config in self:
            payec_config.currency_id = payec_config.company_id.currency_id.id


    name = fields.Char(string='Descripción')
    partner_id = fields.Many2one('res.partner', string='Responsable')
    company_id = fields.Many2one('res.company', string='Company', related='caja_chica_id.company_id',store=True)
    caja_chica_id = fields.Many2one('caja.chica', string='Caja Chica',
        index=True, required=True, readonly=True, states={'draft': [('readonly', False)]},
         auto_join=True, ondelete="cascade")
    journal_id = fields.Many2one('account.journal', string='Diario Contable',store=True,
        related='caja_chica_id.journal_id')
    currency_id = fields.Many2one('res.currency', compute='_compute_currency', string="Currency")
    date = fields.Date(string='Fecha', default=fields.Date.context_today, required=True, readonly=True, states={'draft': [('readonly', False)]},  tracking=True)

    invoice_ids = fields.Many2many('account.move', 'reposicion_caja_chica_table_rel', 'reposicion_caja_chica_id', 'invoice_id', string="Comprobantes")

    domain_invoice_id = fields.Char(compute='_compute_domain_invoice_id')

    amount = fields.Monetary(string='Monto',readonly=True, states={'draft': [('readonly', False)]})
    amount_liquidado = fields.Monetary(string='Monto Liquidado',readonly=True)
    balance = fields.Monetary(string='Saldo')

    mass_payment_ids = fields.One2many('account.payment', 'reposicion_caja_chica_id',
        string='Pagos de Reposicion',  readonly=True)


    state = fields.Selection([
        ('draft', 'Borrador'),('working', 'En proceso'),('posted', 'Hecho'),('cancelled', 'Cancelado')],
        readonly=True, default='draft', tracking=True, copy=False, string="Estado")

    line_ids = fields.One2many('account.payment.invoice', 'payment_id')
    es_inicial = fields.Boolean('Es Reposicion Inicial',readonly=True, states={'draft': [('readonly', False)]})

    type = fields.Selection([
        ('normal', 'Reposición'),
        ('liquidity', 'Liquidación')
    ], string='Tipo', default='normal', required=True)

    reposiciones_facturas_ids = fields.One2many('account.move.reposicion', 'reposicion_caja_chica_id',string='Reposiciones de Facturas')


    @api.depends('invoice_ids')
    def compute_quitar_enlace_invoice_id(self):
        for rec in self:
            pagos = rec.reposiciones_facturas_ids.mapped('payment_id')
            pagos.write({'reposicion_caja_chica_id':False})
            rec.reposiciones_facturas_ids.unlink()


    @api.depends('invoice_ids')
    def compute_poner_enlace_invoice_id(self):
        for rec in self:
            invoice_ids_estan = rec.invoice_ids.filtered(lambda x: x.state not in ('cancel')).ids
            rec.mapped('invoice_ids').compute_amount_pago_reposicion_caja_chica()
            obj = self.env['account.payment.invoice']
            # for factura in invoice_ids_estan:
            lineas_pagos = obj.search([('invoice_id', 'in', invoice_ids_estan)])

            if rec.type == 'normal':
                pagos = lineas_pagos.mapped('payment_id').filtered(lambda x: x.journal_id.caja_chica)
            if rec.type == 'liquidity':
                pagos = lineas_pagos.mapped('payment_id').filtered(lambda x: x.journal_id.fondo_rendir)
            # Incluyendo pagos sin comprobante (Anticipos)
            invoice_ids_estan_sin_comp = set(invoice_ids_estan) - set(lineas_pagos.invoice_id.mapped('id'))
            pagos_sin_comp = self.env['account.payment'].search([('account_move_ids', 'in', invoice_ids_estan_sin_comp)])
            pagos += pagos_sin_comp
            for pago in pagos:
                if pago.state not in ('cancelled'):
                    if pago.journal_id.fondo_rendir or pago.journal_id.caja_chica:
                        if not pago.reposicion_caja_chica_id:
                            pago.write({'reposicion_caja_chica_id': rec.id})
                        pago.crear_account_move_reposicion()
            rec.suma_monto()


    @api.onchange('partner_id','type','caja_chica_id')
    def _compute_domain_invoice_id(self):
        for rec in self:
            fecha=fields.Date.from_string(rec.date).strftime('%Y-%m-%d')
            if rec.type == 'normal':
                rec.domain_invoice_id = json.dumps([('total_pagado_caja_chica','>',0.0),('invoice_date','<=',fecha),('type','in',('in_invoice','in_receipt','out_refund')),('caja_chica_id','=',rec.caja_chica_id.id)])
            if rec.type == 'liquidity':
                rec.domain_invoice_id = json.dumps([('total_pagado_fondo_rendir','>',0.0),('type','in',('in_invoice','in_receipt','out_refund')),('caja_chica_id','=',rec.caja_chica_id.id)])

    def compute_facturas_relacionadas(self):
        for rec in self:
            domain=[('reposicion_caja_chica_id','=',rec.id),('state','=','posted')]
            pagos= self.env['account.payment'].search(domain)
            lista_facturas_ids = pagos.line_ids.mapped("invoice_id")
            facturas_ids = lista_facturas_ids.mapped("id")
            facturas_ids_obj = self.env['account.move'].browse(facturas_ids)
            facturas_ids_obj.compute_amount_pago_reposicion_caja_chica()


    def button_load_deudas_de_pagos(self):
        cr = self.env.cr
        for rec in self:
            domain=[('reposicion_caja_chica_id','=',rec.id),('state','=','posted')]
            pagos= self.env['account.payment'].search(domain)
            invoice_ids_estan=rec.invoice_ids.ids
            lista_facturas_ids = pagos.line_ids.mapped("invoice_id").filtered(lambda x: x.id not in invoice_ids_estan)
            facturas_ids = set(lista_facturas_ids.mapped("id"))
            for f in facturas_ids:
                cr.execute('insert into reposicion_caja_chica_table_rel (reposicion_caja_chica_id,invoice_id) values(%s,%s)',(rec.id,f))

            for pago in pagos:
                pago.crear_account_move_reposicion()
            # rec.flush('reposiciones_facturas_ids')
            rec.suma_monto()


    @api.depends('reposiciones_facturas_ids.monto_pago_actual','invoice_ids.total_pagado')
    def suma_monto(self):
        for rec in self:
            rec.invoice_ids.compute_amount_pago_reposicion_caja_chica()
            amount = sum(rec.invoice_ids.mapped("total_pagado_caja_chica")) or 0.0
            # amount_rendir=sum(rec.invoice_ids.mapped("total_pagado_fondo_rendir")) or 0.0

            amount_rendir = sum(rec.reposiciones_facturas_ids.mapped("monto_pago_actual")) or 0.0

            if rec.es_inicial == False and rec.type == 'normal':
                rec.amount = amount_rendir  # amount
            if rec.type == 'liquidity':
                rec.amount_liquidado = amount_rendir
                rec.balance = rec.amount - rec.amount_liquidado


    def load_varias_deudas_sin_reposicion(self):
        for rec in self:
            # if rec.type=='normal':
            if rec.caja_chica_id and rec.es_inicial==False:
                date='%s'%self.date
                domain = [('invoice_date','<=',date),('caja_chica_id','=',rec.caja_chica_id.id),('type', 'in', ['in_invoice', 'in_receipt'])
                ,('invoice_payment_state', '=', 'paid'),('tiene_repocision','=',False)]
                facturas_ids_obj = self.env['account.move'].search(domain)
                if facturas_ids_obj:
                    facturas_ids = set(facturas_ids_obj.mapped("id"))
                    rec.update({
                    'invoice_ids': [(6, False, facturas_ids)]
                    })
            rec.suma_monto()


    def write(self, values):
        if 'partner_id' not in values:
            if self.type=='normal':
                caja_id = self.env['caja.chica'].browse(values['caja_chica_id']) if 'caja_chica_id' in values else self.caja_chica_id
                values['partner_id'] = caja_id.partner_id.id
        result = super(CajaChicaReposicion, self).write(values)
        return result


    @api.onchange('caja_chica_id','date','amount')
    def onchange_caja_chica(self):
        for rec in self:
            if rec.type=='normal':
                rec.partner_id=self.caja_chica_id.partner_id

    def cancel(self):
        for rec in self:
            if rec.type=='liquidity':
                rec.write({'state':'cancelled'})
            else:
                if rec.mass_payment_ids.filtered(lambda x: x.state == 'posted'):
                    raise UserError("Ya existe un pago registrado para esta reposicion. Debe Borrar ese pago para cancelar la reposición")
                rec.write({'state':'cancelled'})

    def to_draft(self):
        for rec in self:
            if rec.type=='liquidity':
                rec.write({'state':'draft'})
            else:
                rec.write({'state':'draft'})

    def post(self):
        for rec in self:
            if not rec.date:
                raise UserError('Verifique la fecha')
            if not rec.amount:
                raise UserError('Verifique el monto')
            if rec.type=='normal':
                rec.write({'state':'posted'})
            if rec.type=='liquidity':
                if rec.state=='draft':
                    rec.write({'state':'working'})
                elif rec.state=='working':
                    rec.write({'state':'posted'})
                rec.invoice_ids.verifica_reposicion()
