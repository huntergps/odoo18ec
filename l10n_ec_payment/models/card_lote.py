# -*- coding: utf-8 -*-

from odoo import api, fields, models



class LoteTarjetas(models.Model):
    _name = "account.card.lote"
    _description ="Lotes de Tarjeta de Credito"
    _inherit = ['mail.thread', 'mail.activity.mixin']  # Agregar herencia para seguimiento y actividades


    def name_get(self):
        res = []

        for r in self:
            _name=''
            if self.env.context.get('show_id'):
                _name = ' [ %s ]'%r.id or ''
            res.append((r.id, ('%s %s')%(r.name, _name,)))
        return res

    name = fields.Char(string='Nro de Lote', required=True)
    numero_lote = fields.Char(string='Nro de Lote Unico')

    date = fields.Date(string='Fecha', default=fields.Date.context_today, required=True)
    start_at = fields.Datetime(string='Apertura', readonly=True)
    stop_at = fields.Datetime(string='Cierre', readonly=True, copy=False)
    journal_id = fields.Many2one('account.journal', string='Tipo de Tarjeta de Crédito',domain="[('type', '=', 'customer_ccard')]")
    emisor_name = fields.Char(related='journal_id.name',readonly=True)
    state = fields.Selection([
        ('open', 'Abierto'),
        ('close', 'Cerrado'),
        ('pending', 'Pendiente'),
        ('done', 'Liquidado'),
    ], string='Estado', default='open', required=True)
    comment = fields.Text(string="Comentarios")
    amount = fields.Float('Total', compute='_compute_totals',store=True)
    liquidado = fields.Float('Liquidado', compute='_compute_totals',store=True)
    saldo = fields.Float('Saldo', compute='_compute_totals',store=True)
    recibos_count = fields.Integer(compute='_compute_vouchers_count', string='Nro de Vales')
    recibos_ids = fields.One2many('account.payment', 'lote_id',  string='Recibos en Pagos',
        domain=[('state','not in',('draft','cancelled','rejected'))])
    voucher_ids = fields.One2many('account.advance.line', 'lote_id',  string='Recibos en Anticipos',
        domain=[('state','not in',('draft','cancelled','rejected'))])
    cerrado_en_pos = fields.Boolean(string="Lote Cerrado en POS", default=False)

    _sql_constraints = [('name_uniq', 'unique (name,date)', 'El nro de Lote por fecha debe ser unico!')]

    def obtener_nro_lote(self):
        self._compute_numero_lote()
        return True


    @api.depends('name')
    def _compute_numero_lote(self):
        for rec in self:
            date= str("%s"%rec.date).replace("-","")

            print(date)
            if rec.name and rec.date:
                try:
                    rec.numero_lote = str(int(rec.name))+date
                except Exception as e:
                    rec.numero_lote = ""
            else:
                rec.numero_lote = ""

    @api.onchange('recibos_ids')
    def _compute_totals(self):
        for lote in self:
            amount = liquidado = saldo = 0.0
            lote.amount = amount
            lote.liquidado = liquidado
            lote.saldo = amount-liquidado

    @api.onchange('recibos_ids')
    def _compute_vouchers_count(self):
        for lote in self:
            lote.recibos_count = len(lote.recibos_ids)

    def action_cerrar(self):
        for rec in self:
            rec.write({'state': 'close', 'stop_at': fields.Datetime.now()})
            print('Cerrar')




# class LoteTarjetasStament(models.Model):
#
#     _name = "account.card.statement"
#     _description = "Extractos Bancarios"
#     _order = "date desc, id desc"
#     _inherit = ['mail.thread']
#
#     name = fields.Char(string='Reference', states={'open': [('readonly', False)]}, copy=False, readonly=True)
#     reference = fields.Char(string='External Reference', states={'open': [('readonly', False)]}, copy=False, readonly=True, help="Used to hold the reference of the external mean that created this statement (name of imported file, reference of online synchronization...)")
#     date = fields.Date(required=True, states={'confirm': [('readonly', True)]}, index=True, copy=False, default=fields.Date.context_today)
#     date_done = fields.Datetime(string="Closed On")
#     balance_start = fields.Monetary(string='Starting Balance', states={'confirm': [('readonly', True)]}, default=_default_opening_balance)
#     balance_end_real = fields.Monetary('Ending Balance', states={'confirm': [('readonly', True)]})
#     accounting_date = fields.Date(string="Accounting Date", help="If set, the accounting entries created during the bank statement reconciliation process will be created at this date.\n"
#         "This is useful if the accounting period in which the entries should normally be booked is already closed.")
#     state = fields.Selection([('open', 'New'), ('confirm', 'Validated')], string='Status', required=True, readonly=True, copy=False, default='open')
#     currency_id = fields.Many2one('res.currency', compute='_compute_currency', string="Currency")
#     journal_id = fields.Many2one('account.journal', string='Journal', required=True, states={'confirm': [('readonly', True)]}, default=_default_journal)
#     journal_type = fields.Selection(related='journal_id.type', help="Technical field used for usability purposes")
#     company_id = fields.Many2one('res.company', related='journal_id.company_id', string='Company', store=True, readonly=True,
#         default=lambda self: self.env.company)
#
#     total_entry_encoding = fields.Monetary('Transactions Subtotal', compute='_end_balance', store=True, help="Total of transaction lines.")
#     balance_end = fields.Monetary('Computed Balance', compute='_end_balance', store=True, help='Balance as calculated based on Opening Balance and transaction lines')
#     difference = fields.Monetary(compute='_end_balance', store=True, help="Difference between the computed ending balance and the specified ending balance.")
#
#     line_ids = fields.One2many('account.bank.statement.line', 'statement_id', string='Statement lines', states={'confirm': [('readonly', True)]}, copy=True)
#     move_line_ids = fields.One2many('account.move.line', 'statement_id', string='Entry lines', states={'confirm': [('readonly', True)]})
#     move_line_count = fields.Integer(compute="_get_move_line_count")
#
#     all_lines_reconciled = fields.Boolean(compute='_check_lines_reconciled')
#     user_id = fields.Many2one('res.users', string='Responsible', required=False, default=lambda self: self.env.user)
#     cashbox_start_id = fields.Many2one('account.bank.statement.cashbox', string="Starting Cashbox")
#     cashbox_end_id = fields.Many2one('account.bank.statement.cashbox', string="Ending Cashbox")
#     is_difference_zero = fields.Boolean(compute='_is_difference_zero', string='Is zero', help="Check if difference is zero.")
#
#     def unlink(self):
#
#         for statement in self:
#             if statement.state != 'open':
#                 raise UserError(_('In order to delete a bank statement, you must first cancel it to delete related journal items.'))
#             # Explicitly unlink bank statement lines so it will check that the related journal entries have been deleted first
#             statement.line_ids.unlink()
#         return super(LoteTarjetasStament, self).unlink()
#
#
#
# class LoteTarjetasStamentLine(models.Model):
#     _name = "account.card.staments.line"
#     _description = "Linea de Extractos Bancarios"
#     _order = "date desc, id desc, sequence"
#
#     name = fields.Char(string='Nro de Lote', required=True)
#     fecha_pago = fields.Date(string='Fecha', default=fields.Date.context_today, required=True)
#     tipo = fields.Char(string='Tipo')
#     nro = fields.Char(string='Nro de Comprobante')
#     adquiriente = fields.Char(string='Adquiriente')
#     comment = fields.Text(string="Comentarios")
#     total = fields.Float('Total')
#     base0 = fields.Float('Base 0')
#     base_imponible = fields.Float('Base Imponible')
#     iva = fields.Float('IVA')
#     valor_pagado = fields.Float('Valor Pagado')
#     ret_fuente = fields.Float('Ret. Fuente')
#     ret_iva = fields.Float('Ret. IVA')
#     ret_fuente = fields.Float('Ret. Fuente')
#     comision = fields.Float('Comisión')
#     comision_iva = fields.Float('Comisión IVA')
#     liquidado = fields.Float('Liquidado')
#     state = fields.Selection([
#         ('conciliado', 'Conciliado'),
#         ('no_conciliado', 'No Conciliado'),
#     ], string='Estado', default='open', required=True)
#     unique_import_id = fields.Char(string='Importación ID', readonly=True, copy=False)
#
#     _sql_constraints = [
#         ('unique_import_id', 'unique (unique_import_id)', 'Las transacciones de un tarjeta solo se pueden importar una vez !')
#     ]
