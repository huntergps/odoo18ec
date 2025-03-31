# -*- coding: utf-8 -*-
"""
Este módulo define el modelo de anticipos para pagos en Ecuador.
Organizado en secciones para mejor mantenibilidad:
1. Definición del modelo y campos
2. Métodos de ayuda
3. Métodos de cálculo
4. Métodos de restricción
5. Métodos de bajo nivel
6. Métodos de sincronización
7. Métodos de negocio
"""
from odoo import models, fields, api, _, Command
from odoo.exceptions import UserError, ValidationError
from odoo.tools.misc import format_date, formatLang
from odoo.tools import create_index
from odoo.tools import SQL
from odoo.tools.float_utils import float_compare, float_is_zero


class AccountAdvance(models.Model):
    """Modelo para gestionar anticipos de pagos"""
    _name = 'account.advance'
    _inherit = ['mail.thread.main.attachment', 'mail.activity.mixin']
    _description = "Anticipos"
    _order = "date desc, name desc"
    _check_company_auto = True

    # -------------------------------------------------------------------------
    # CAMPOS DE NEGOCIO
    # -------------------------------------------------------------------------
    name = fields.Char(string="Numero", compute='_compute_name', store=True)
    date = fields.Date(string="Fecha", default=fields.Date.context_today, required=True, tracking=True)
    date_estimated = fields.Date(string="Fecha Estimada", default=fields.Date.context_today, required=True, tracking=True)
    company_id = fields.Many2one(
        comodel_name='res.company',
        compute='_compute_company_id', store=True, readonly=False, precompute=True,
        index=False,  # covered by account_advance_journal_id_company_id_idx
        required=True
    )
    state = fields.Selection(
        selection=[
            ('draft', "Borrador"),
            ('posted', "Procesado"),
            ('canceled', "Cancelado"),
            ('rejected', "Rechazado"),
        ],
        required=True,
        default='draft',
        compute='_compute_state', store=True, readonly=False,
        copy=False,
    )

    # -------------------------------------------------------------------------
    # CAMPOS DE MÉTODO DE ANTICIPOS
    # -------------------------------------------------------------------------
    amount = fields.Monetary(string="Monto", currency_field='currency_id', compute='_compute_amount', store=True)
    amount_used = fields.Monetary(string="Monto Usado", currency_field='currency_id', compute='_compute_amount_used', store=True)
    amount_available = fields.Monetary(string="Monto Disponible", currency_field='currency_id', compute='_compute_amount_available', store=True)
    amount_returned = fields.Monetary(string="Monto Devuelto", currency_field='currency_id', compute='_compute_amount_returned', store=True)
    amount_signed = fields.Monetary(
        currency_field='currency_id', compute='_compute_amount_signed', tracking=True,
        help='Valor negativo del campo de monto si Tipo de Anticipo es a Acreedor')

    advance_type = fields.Selection([
        ('outbound', 'Anticipo a Acreedor'),
        ('inbound', 'Recibir de Cliente'),
    ], string='Tipo de Anticipo', default='inbound', required=True, tracking=True)
    
    partner_type = fields.Selection([
        ('customer', 'Cliente'),
        ('supplier', 'Acreedor'),
    ], default='customer', tracking=True, required=True)
    
    reference = fields.Char(string="Glosa", copy=False, tracking=True)
    
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        compute='_compute_currency_id', store=True, readonly=False, precompute=True,
        help="The advance's currency.")
    company_currency_id = fields.Many2one(string="Company Currency", related='company_id.currency_id')
    
    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string="Cliente / Acreedor",
        readonly=False, ondelete='restrict',
        domain="['|', ('parent_id','=', False), ('is_company','=', True)]",
        tracking=True,
        check_company=True)
    

    payment_ids = fields.One2many('account.payment', 'advance_id', string='Pagos Relacionados')
    advance_line_ids = fields.One2many('account.advance.line', 'advance_id', 
                                        string='Formas de Pago', copy=True)
    cashier_id = fields.Many2one('res.users', string='Cajero', default=lambda self: self.env.user,
                                required=True, tracking=True)

    move_ids = fields.One2many(
        comodel_name='account.move',
        inverse_name='origin_advance_id',
        string='Asientos Contables',
        readonly=True,
        copy=False)
        
    move_count = fields.Integer(
        compute='_compute_move_count',
        string='Número de Asientos')

    # -------------------------------------------------------------------------
    # CAMPOS DE VISUALIZACIÓN
    # -------------------------------------------------------------------------
    advance_receipt_title = fields.Char(
        compute='_compute_advance_receipt_title'
    )
    attachment_ids = fields.One2many('ir.attachment', 'res_id', string='Attachments')

    # -------------------------------------------------------------------------
    # MÉTODOS DE RESTRICCIÓN
    # -------------------------------------------------------------------------
    # @api.constrains('amount')
    # def _check_amount_positive(self):
    #     for advance in self:
    #         if advance.amount <= 0:
    #             raise ValidationError(_("El monto del anticipo debe ser mayor a 0."))

    @api.constrains('date_estimated', 'date')
    def _check_date_estimated(self):
        for advance in self:
            if advance.date_estimated < advance.date:
                raise ValidationError(_("La fecha estimada debe ser mayor que la fecha de registro."))

    @api.constrains('reference')
    def _check_reference_length(self):
        for advance in self:
            if advance.reference and len(advance.reference) < 30:
                raise ValidationError(_('La glosa debe contener al menos 30 caracteres.'))


    # -------------------------------------------------------------------------
    # INICIALIZACIÓN
    # -------------------------------------------------------------------------
    def init(self):
        super().init()
        create_index(
            self.env.cr,
            indexname='account_advance_id_company_id_idx',
            tablename='account_advance',
            expressions=['company_id']
        )

    # -------------------------------------------------------------------------
    # MÉTODOS DE CÁLCULO
    # -------------------------------------------------------------------------

    @api.depends('payment_type')
    def _compute_available_journal_ids(self):
        """
        Get all journals having at least one payment method for inbound/outbound depending on the payment_type.
        """
        journals = self.env['account.journal'].search([
            '|',
            ('company_id', 'parent_of', self.env.company.id),
            ('company_id', 'child_of', self.env.company.id),
            ('type', 'in', ('bank', 'cash', 'credit','advance','cross')),
        ])
        print("***** journals: ",journals)
        for pay in self:
            if pay.payment_type == 'inbound':
                pay.available_journal_ids = journals.filtered('inbound_payment_method_line_ids')
            else:
                pay.available_journal_ids = journals.filtered('outbound_payment_method_line_ids')


    @api.depends('state')
    def _compute_name(self):
        for advance in self:
            advance_seq = 'account.advance.outbound'
            if advance.advance_type=='inbound':
                advance_seq = 'account.advance.inbound'
            if advance.id and not advance.name and advance.state in ('in_process', 'paid'):
                advance.name = (
                    self.env['ir.sequence'].with_company(advance.company_id).next_by_code(
                        advance_seq,
                        sequence_date=advance.date,
                    )
                )

    @api.depends('partner_id', 'advance_type')
    def _compute_company_id(self):
        for advance in self:
            advance.company_id = (self.env.company)._accessible_branches()[:1]

    @api.depends('payment_ids.state')
    def _compute_state(self):
        for advance in self:
            if not advance.state:
                advance.state = 'draft'
            # Ya no consideramos payment_ids para determinar el estado del anticipo

    @api.depends('amount', 'advance_type')
    def _compute_amount_signed(self):
        for advance in self:
            if advance.advance_type == 'outbound':
                advance.amount_signed = -advance.amount
            else:
                advance.amount_signed = advance.amount

    @api.depends('advance_type')
    def _compute_currency_id(self):
        for pay in self:
            pay.currency_id = pay.company_id.currency_id

    @api.depends('amount',  'currency_id', 'advance_type')
    def _compute_advance_receipt_title(self):
        """ To override in order to change the title displayed on the advance receipt report """
        self.advance_receipt_title = _('Anticipo')

    @api.depends('advance_line_ids.amount')
    def _compute_amount(self):
        for advance in self:
            if advance.advance_line_ids:
                advance.amount = sum(advance.advance_line_ids.mapped('amount'))
            else:
                advance.amount = advance.amount if advance.amount else 0.0

    @api.depends('payment_ids.amount', 'payment_ids.state')
    def _compute_amount_used(self):
        for advance in self:
            payments = advance.payment_ids.filtered(
                lambda p: p.state in ('posted', 'reconciled', 'sent')
            )
            advance.amount_used = sum(payments.mapped('amount'))

    @api.depends('payment_ids.amount', 'payment_ids.state', 'payment_ids.payment_type')
    def _compute_amount_returned(self):
        for advance in self:
            returned_payments = advance.payment_ids.filtered(
                lambda p: p.state in ('posted', 'reconciled', 'sent') and 
                          ((p.payment_type == 'outbound' and advance.advance_type == 'inbound') or
                           (p.payment_type == 'inbound' and advance.advance_type == 'outbound'))
            )
            advance.amount_returned = sum(returned_payments.mapped('amount'))

    @api.depends('amount', 'amount_used', 'amount_returned')
    def _compute_amount_available(self):
        for advance in self:
            advance.amount_available = advance.amount - advance.amount_used - advance.amount_returned
            

    @api.depends('state', 'advance_type', 'name')
    def _compute_display_name(self):
        for advance in self:
            advance.display_name = advance.name or _('Draft Advance')

    @api.depends('move_ids')
    def _compute_move_count(self):
        for advance in self:
            advance.move_count = len(advance.move_ids)

    # -------------------------------------------------------------------------
    # MÉTODOS DE RESTRICCIÓN
    # -------------------------------------------------------------------------


    @api.constrains('advance_line_ids')
    def _check_payment_methods_amount(self):
        for advance in self:
            if advance.state == 'draft':
                return
            total_methods = sum(advance.advance_line_ids.mapped('amount'))
            if float_compare(total_methods, advance.amount, precision_rounding=advance.currency_id.rounding) != 0:
                raise ValidationError(_("El monto total de las formas de pago debe ser igual al monto del anticipo."))

    @api.constrains('advance_line_ids', 'amount')
    def _check_payment_methods_total(self):
        for advance in self:
            if advance.state != 'draft' and advance.advance_line_ids:
                total_payment_methods = sum(method.amount for method in advance.advance_line_ids)
                if float_compare(total_payment_methods, advance.amount, precision_rounding=advance.currency_id.rounding) != 0:
                    raise ValidationError(_('El monto total de las formas de pago debe ser igual al monto del anticipo.'))

    # -------------------------------------------------------------------------
    # MÉTODOS DE BAJO NIVEL
    # -------------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        advances = super().create(vals_list)
        return advances

    def _get_outstanding_account(self, advance_type):
        account_ref = 'account_journal_advance_debit_account_id' if advance_type == 'inbound' else 'account_journal_advance_credit_account_id'
        chart_template = self.with_context(allowed_company_ids=self.company_id.root_id.ids).env['account.chart.template']
        outstanding_account = (
            chart_template.ref(account_ref, raise_if_not_found=False)
            or self.company_id.transfer_account_id
        )
        if not outstanding_account:
            raise UserError(_("No outstanding account could be found to make the advance"))
        return outstanding_account

    def write(self, vals):
        # OVERRIDE - Eliminada la lógica de sincronización con el asiento
        res = super().write(vals)
        return res

    def unlink(self):
        # OVERRIDE - No es necesario borrar el asiento directamente, ya que se borrará mediante los métodos de pago
        res = super().unlink()
        return res

    # -------------------------------------------------------------------------
    # SINCRONIZACIÓN account.advance -> account.move
    # -------------------------------------------------------------------------

    def _get_advance_receipt_report_values(self):
        self.ensure_one()
        return {
            'display_invoices': True,
            'display_advance_method': True,
        }

    # -------------------------------------------------------------------------
    # MÉTODOS DE NEGOCIO
    # -------------------------------------------------------------------------

    def action_post(self):
        for advance in self:
            if not advance.advance_line_ids:
                raise UserError(_("Debe especificar al menos una forma de pago para el anticipo."))
            if advance.reference:                
                if len(advance.reference) < 30:
                    raise UserError('La glosa debe contener al menos 30 caracteres')   
            else:
                raise UserError('La glosa es obligatoria')
             
            if advance.amount <= 0:
                raise UserError('El monto debe ser mayor que 0')
            if advance.date_estimated <= advance.date:
                raise UserError('La fecha estimada debe ser mayor que la fecha del registro')
            
            # Publicar todos los métodos de pago
            advance.advance_line_ids.action_post()
        
        self.filtered(lambda pay: pay.state in {False, 'draft'}).state = 'posted'
        
    def action_validate(self):
        # Este método ya no es necesario ya que no usamos el estado 'paid'
        pass

    def action_reject(self):
        self.state = 'rejected'

    def action_cancel(self):
        # Cancelar todos los métodos de pago y sus asientos
        for advance in self:
            for payment_method in advance.advance_line_ids:
                if payment_method.move_id and payment_method.move_id.state != 'draft':
                    payment_method.move_id.button_cancel()
        
        self.state = 'canceled'

    def action_draft(self):
        # Pasar a borrador todos los métodos de pago y sus asientos
        for advance in self:
            advance.advance_line_ids.action_draft()
        
        self.state = 'draft' 

    def button_open_invoices(self):
        self.ensure_one()
        return (self.advance_ids).with_context(
            create=False
        )._get_records_action(
            name=_("Paid Invoices"),
        )

    def button_open_bills(self):
        self.ensure_one()

        action = {
            'name': _("Paid Bills"),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'context': {'create': False},
        }
        if len(self.reconciled_bill_ids) == 1:
            action.update({
                'view_mode': 'form',
                'res_id': self.reconciled_bill_ids.id,
            })
        else:
            action.update({
                'view_mode': 'list,form',
                'domain': [('id', 'in', self.reconciled_bill_ids.ids)],
            })
        return action

    def button_open_journal_entries(self):
        """Ver todos los asientos contables relacionados con este anticipo"""
        self.ensure_one()
        action = {
            'name': _('Asientos Contables'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'context': {'create': False, 'default_origin_advance_id': self.id},
            'domain': [('origin_advance_id', '=', self.id)],
        }
        
        if self.move_count == 1:
            action.update({
                'view_mode': 'form',
                'res_id': self.move_ids[0].id,  # Acceder al primer registro usando índices
            })
        else:
            action.update({
                'view_mode': 'list,form',  # Cambiado de 'tree,form' a 'list,form'
            })
        return action


    def action_print_receipt(self):
        """Imprimir recibo de anticipo"""
        self.ensure_one()
        return self.env.ref('l10n_ec_payment.action_report_advance_receipt').report_action(self)
