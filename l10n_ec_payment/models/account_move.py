# Part of Odoo. See LICENSE file for full copyright and licensing details.
from odoo import models, fields, api, _, Command

# a lot of SQL queries
class AccountMove(models.Model):
    _inherit = ['account.move']

    advance_line_ids = fields.One2many('account.advance.line', 'move_id', string='Lineas de Anticipos')
    cheque_postfechado_id = fields.Many2one('cheque.recibido', string="Cheque Postfechado", copy=False)

    total_pagado_caja_chica = fields.Monetary(
        string='Total Pagado Caja Chica',
        compute='_compute_total_pagado_caja_chica',
        store=True
    )
    total_pagado_fondo_rendir = fields.Monetary(
        string='Total Pagado Fondo Rendir',
        compute='_compute_total_pagado_fondo_rendir',
        store=True
    )

    @api.depends('line_ids.debit', 'line_ids.credit', 'line_ids.currency_id', 'line_ids.amount_currency', 'line_ids.amount_residual', 'line_ids.amount_residual_currency', 'line_ids.payment_id.state')
    def _compute_total_pagado_caja_chica(self):
        for move in self:
            total = 0.0
            for line in move.line_ids:
                if line.journal_id.caja_chica and line.account_id.account_type in ('asset_receivable', 'liability_payable'):
                    total += line.debit - line.credit
            move.total_pagado_caja_chica = total

    @api.depends('line_ids.debit', 'line_ids.credit', 'line_ids.currency_id', 'line_ids.amount_currency', 'line_ids.amount_residual', 'line_ids.amount_residual_currency', 'line_ids.payment_id.state')
    def _compute_total_pagado_fondo_rendir(self):
        for move in self:
            total = 0.0
            for line in move.line_ids:
                if line.journal_id.fondo_rendir and line.account_id.account_type in ('asset_receivable', 'liability_payable'):
                    total += line.debit - line.credit
            move.total_pagado_fondo_rendir = total

    @api.depends('reposicion_caja_chica_ids.state', 'reposicion_caja_chica_ids')
    def verifica_reposicion(self):
        for record in self:
            num=False
            repos=record.reposicion_caja_chica_ids.filtered(lambda repo: repo.state=='posted')
            record.tiene_repocision = len(repos)>0



    # === Advance fields === #
    origin_advance_id = fields.Many2one(  # the advance this is the journal entry of
        comodel_name='account.advance',
        string="Anticipo",
        index='btree_not_null',
        copy=False,
        check_company=True,
    )


    def action_open_business_doc(self):
        if self.origin_advance_id:
            name = _("Anticipo")
            res_model = 'account.advance'
            res_id = self.origin_advance_id.id
            return {
                'name': name,
                'type': 'ir.actions.act_window',
                'view_mode': 'form',
                'views': [(False, 'form')],
                'res_model': res_model,
                'res_id': res_id,
                'target': 'current',
            }
        else:
            return super().action_open_business_doc()


class AccountInvoiceFondoRendir(models.Model):
    _name = 'account.move.reposicion'
    _description = 'Reposiciones de Facturas'

    reposicion_caja_chica_id = fields.Many2one('caja.chica.reposicion',string="Reposicion de Caja Chica", ondelete="cascade")
    comprobante_pago_id = fields.Many2one('account.payment', string='Comprobante de Pago',ondelete="cascade")
    move_id = fields.Many2one('account.move', string="Factura")
    invoice_type = fields.Selection(selection=[
            ('entry', 'Journal Entry'),
            ('out_invoice', 'Customer Invoice'),
            ('out_refund', 'Customer Credit Note'),
            ('in_invoice', 'Vendor Bill'),
            ('in_refund', 'Vendor Credit Note'),
            ('out_receipt', 'Sales Receipt'),
            ('in_receipt', 'Purchase Receipt'),
        ], string='Tipo', related='move_id.move_type')

    
    comprobante_sri_id = fields.Many2one('l10n_latam.document.type', string='Comprobante',readonly=True )
    secuencial = fields.Char( string='Secuencial',readonly=True )
    date = fields.Date(string="Fecha" ,readonly=True)
    due_date = fields.Date(string="Vencimiento" ,readonly=True)
    monto_original = fields.Float(string="Monto original" ,readonly=True)
    monto_saldo = fields.Float(string="Saldo",readonly=True)
    monto_diponible = fields.Float('Disponible',compute='get_monto_disponible', readonly=True)
    currency_id= fields.Many2one('res.currency',string='Moneda',related='move_id.company_id.currency_id', readonly=True)
    partner_id= fields.Many2one(string='Entidad',related='move_id.partner_id', readonly=True)
    total_sri = fields.Monetary(string="Total Factura", related='move_id.amount_total')
    amount_residual = fields.Monetary(string="Total Pendiente", related='move_id.amount_residual')
    total_retenido_now = fields.Monetary(string="Total Retenido al Pagar")
    amount_residual_now = fields.Monetary(string="Total Pendiente al Pagar")
    pago_referencia = fields.Char(string="Referencia" ,readonly=True)
    tipo_compra = fields.Char(string="Tipo Compra" ,readonly=True)
    monto_pago_actual = fields.Float(string="Pago Actual", default=0.0)





    @api.onchange('monto_saldo','monto_pago_actual')
    def get_monto_disponible(self):
        for line in self:

            dif = line.monto_saldo - line.monto_pago_actual
            if dif<0:
                line.monto_pago_actual =line.monto_saldo
            line.monto_diponible = line.monto_saldo - line.monto_pago_actual

