# -*- coding: utf-8 -*-

from odoo.exceptions import UserError, ValidationError
from odoo import api, fields, models, _
from datetime import datetime, timedelta

class ChequeRecibido(models.Model):
    _name = "cheque.recibido"
    _description = "Cheque Recibido"
    _inherit = ['mail.thread', 'mail.activity.mixin']

    # -------------------------------------------------------------------------
    # CAMPOS DE NEGOCIO
    # -------------------------------------------------------------------------
    company_id = fields.Many2one(
        comodel_name='res.company',
        compute='_compute_company_id', store=True, readonly=False, precompute=True,
        index=False,  # covered by account_advance_journal_id_company_id_idx
        required=True
    )
    comprobante_pago_id = fields.Many2one('account.payment', string='Comprobante de Pago',
        index=True,  readonly=True, auto_join=True, ondelete="cascade")
    pago_id = fields.Many2one('account.payment', string='Pago Nro')
    name = fields.Char(string='Cheque Ref', readonly=True, tracking=True)
    cheque_no = fields.Char(string='Cheque No.', readonly=True, tracking=True)
    journal_id = fields.Many2one('account.journal', string="Caja de Recepción", tracking=True)
    partner_bank_account_id = fields.Many2one('res.partner.bank', string="Cuenta Bancaria", readonly=True,
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]")
    cheque_date = fields.Date(string='Fecha del Cheque', readonly=True, tracking=True)
    cheque_date_reception = fields.Date(string='Fecha de Recepción', readonly=True)
    cheque_date_efective = fields.Date(string='Fecha Efectiva de Cobro', readonly=True, tracking=True)
    hold_date = fields.Date(string='Fecha de Custodia', readonly=True)
    return_date = fields.Date(string='Fecha de Devolución', readonly=True)
    cancel_date = fields.Date(string='Fecha de Cancelación', readonly=True)
    partner_id = fields.Many2one('res.partner', string="Cliente", readonly=True)
    partner_account_id = fields.Many2one('account.account', string="Cuenta contable", readonly=True)
    account_move_ids = fields.Many2many('account.move','cheque_recibido_move_rel', 'cheque_id', 'move_id', 'Asientos relacionados', readonly=True)
    move_line_ids = fields.One2many('account.move.line', 'cheque_id', readonly=True, copy=False)
    state = fields.Selection([
        ('received', 'Recibido'),
        ('hold', 'En Custodia'),
        ('sent', 'Enviado'),
        ('desposited', 'Depositado'),
        ('cleared', 'Cobrado'),
        ('returned', 'Devuelto'),
        ('cancelled', 'Cancelado'),
    ], string='Estado',tracking=True, default='received', readonly=True)
    comment = fields.Text(string="Comentarios")
    amount = fields.Float('Monto', readonly=True)
    type_mov = fields.Selection([
        ('current', 'Ordinaria'),
        ('advance', 'Anticipo'),
    ], string='Tipo de Transación', default = 'current', readonly=True)
    currency_id = fields.Many2one('res.currency', string='Moneda', required=True,
        readonly=True, default=lambda self: self.env.company.currency_id)
    es_posfechado = fields.Boolean('Es posfechado', compute='verifica_fechas', store=True)
    postfechado_deudas_ids = fields.One2many('account.move', 'cheque_postfechado_id', readonly=True, copy=False)

    # -------------------------------------------------------------------------
    # MÉTODOS DE AYUDA
    # -------------------------------------------------------------------------
    @api.depends('partner_id', 'pago_id')
    def _compute_company_id(self):
        for advance in self:
            advance.company_id = (self.env.company)._accessible_branches()[:1]

    @api.depends('cheque_date_reception', 'cheque_date_efective')
    def verifica_fechas(self):
        for rec in self:
            fecha_recepcion = rec.cheque_date_reception
            fecha_efectiva = rec.cheque_date_efective
            alert_days = rec.company_id.l10n_ec_payment_cheque_alert_inbound or 3            
            dias_diff = fecha_recepcion - fecha_efectiva
            es_posfechado = dias_diff < 0
            rec.es_posfechado = es_posfechado

    def _get_default_journal_id(self):
        journal_obj = self.env['account.journal']
        journal_id=None
        journal_ids = journal_obj.search([('type', '=', 'sale')])
        journal_id = journal_ids and journal_ids[0].id or False
        return journal_id

    # -------------------------------------------------------------------------
    # MÉTODOS DE NEGOCIO
    # -------------------------------------------------------------------------
    def create_deuda_postechado(self):
        for rec in self:
            vals_asiento = {
                'cheque_postfechado_id': rec.id,
                'ref': 'Cheque posfechado %s' % (rec.name),
                'name': '/',
                'move_type': 'out_receipt',
                'narration': 'Generado desde Cheque posfechado %s' % (rec.name),
                'partner_id': rec.partner_id.id,
                'invoice_date': rec.cheque_date_reception,
                'invoice_date_due': rec.cheque_date,
                'journal_id': self._get_default_journal_id(),
                'invoice_user_id': self.env.user.id,
                'invoice_origin': 'Cheque posfechado ID #%s' % rec.id,
                'comprobante_id': 2,
                'invoice_line_ids': [],
            }
            cheques_post_deuda_account_id = rec.journal_id.default_debit_account_id.id or False
            if not cheques_post_deuda_account_id:
                raise UserError("Debe configurar la cuenta contable del Diario %s para el registro de deudas generadas por cheques postfechados"%rec.journal_id.name)

            filter=[('cheque_postfechado_id','=',rec.id ),('state','!=','cancel')]
            facts = self.env['account.move'].search(filter)
            if len(facts)>0:
                raise UserError("Ya existe una deuda generada para este cheque")
            else:
                valsDeuda = {
                            'ref': 'Cheque posfechado %s'%(rec.name),
                            'account_id':cheques_post_deuda_account_id,
                            'quantity': 1,
                            'price_unit': rec.amount,
                            'tax_ids': [],
                            }
                vals_asiento['saldo_migrado'] = False
                vals_asiento['invoice_line_ids'].append((0, 0, valsDeuda))
                if rec.amount>0:
                    ch_deuda = self.env['account.move'].create(vals_asiento)
                    ch_deuda.action_post()

    @api.model_create_multi
    def create(self, vals_list):
        if not isinstance(vals_list, list):
            vals_list = [vals_list]
        records = super(ChequeRecibido, self).create(vals_list)
        return records

    def unlink(self):
        if self.filtered(lambda cheque: cheque.state not in ('hold', 'received', 'cancelled')):
            raise UserError("No se puede borrar un cheque en este estado: %s" % self.state)
        super(ChequeRecibido, self).unlink()
        return {
            'type': 'ir.actions.client',
            'name': 'Cheques Recibidos',
            'tag': 'reload',
            'params': {'menu_id': self.env.ref('mass_payment.menu_action_cheque_recibido').id},
        }

    def _check_pending(self):
        today = fields.Date.context_today(self)
        today_date = datetime.strptime(today, '%Y-%m-%d').date()
        cheques = ""
        for record in self.search([('state', 'in', ('issued', 'hold'))]):
            if record.cheque_date < today and record.state == 'issued':
                record.write({'state': 'pending'})

            elif record.state == 'hold'and record.hold_date < today:
                record.write({'state': 'pending'})
        alert_days = self.company_id.l10n_ec_payment_cheque_alert_outbound or 3                    
        alert_date = today_date + timedelta(days=alert_days)
        alert_cheques = []
        for record in self.search([('state', 'in', ('issued', 'hold'))]):
            if record.cheque_date == str(alert_date) and record.state == 'issued':
                cheques = cheques + record.name + ", "
                alert_cheques.append(record)
            elif record.state == 'hold' and record.hold_date == str(alert_date):
                cheques = cheques + record.name + ", "
                alert_cheques.append(record)

        if cheques != "":
            cheques = cheques[:-2]
            cheques = cheques + "\n"
            cheque_email  = self.company_id.l10n_ec_payment_cheque_email           
            
            vals = {'state': 'outgoing',
                    'subject': 'Outbound Cheques Pending List',
                    'body_html': """<div>
                                        <p>Hello,</p>
                                        <p>This is a system generated reminder mail. The following outbound cheques are pending.</p>
                                    </div>
                                    <blockquote>%s</blockquote>
                                    <div>Thank You</div>""" % (cheques),
                    'email_to': cheque_email,
                    }
            email_id = self.env['mail.mail'].create(vals)
            email_id.send()

    def immediate_make_pending(self):
        for record in self.search([]):
            record.make_pending()

    def make_pending(self):
        today = fields.Date.context_today(self)
        if self.cheque_date < today and self.state == 'issued':
            self.write({'state': 'pending'})
        elif self.state == 'hold' and self.hold_date < today:
            self.write({'state': 'pending'})

    def print_cheque(self):
        return

    def amount_to_text(self, amount):
        return self.env.user.currency_id.amount_to_text(amount)

    def issue_cheque(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Emitir Cheque',
            'view_mode': 'form',
            'res_model': 'issue.cheque.wizard',
            'target': 'new',
            'context': 'None'
        }

    def clear_cheque(self):
        view = self.env.ref('mass_payment.wizard_clear_cheque')
        return {
            'type': 'ir.actions.act_window',
            'name': 'Cheque Cobrado',
            'view_id': view.id,
            'view_mode': 'form',
            'res_model': 'clear.cheque',
            'target': 'new',
            'context': 'None'
        }

    def hold_cheque(self):
        view = self.env.ref('mass_payment.wizard_clear_cheque3')
        return {
            'type': 'ir.actions.act_window',
            'name': 'Cheque en Mano',
            'view_id': view.id,
            'view_mode': 'form',
            'res_model': 'clear.cheque',
            'target': 'new',
            'context': 'None'
        }

    def cancel_cheque(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Cancelación de Cheque',
            'view_mode': 'form',
            'res_model': 'cancel.cheque',
            'target': 'new',
            'context': 'None'
        }

    def return_cheque(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Devolución de Cheque',
            'view_mode': 'form',
            'res_model': 'return.cheque',
            'target': 'new',
            'context': 'None'
        }
