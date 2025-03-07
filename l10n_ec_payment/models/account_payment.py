from odoo import fields, models, api, Command, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.misc import format_date


class AccountPayment(models.Model):
    _inherit = ['account.payment']

    advance_id = fields.Many2one('account.advance', string='Anticipo')

    type_mov = fields.Selection(selection_add=[
        ('advance', 'Anticipo'),
        ('cross', 'Cruce de Cartera'),
        ('other', 'Otros Pagos'),
    ], ondelete={'advance': 'set default','cross': 'set default','other': 'set default'})


    # @api.depends('payment_method_line_id')
    # def _compute_outstanding_account_id(self):
    #     for pay in self:
    #         if pay.type_mov=='current':
    #             pay.outstanding_account_id = pay.payment_method_line_id.payment_account_id
    #         else:
    #             pay.outstanding_account_id = pay.journal_id.suspense_account_id


    @api.depends('company_id', 'type_mov','payment_type')
    def _compute_journal_id(self):
        for payment in self:
            company = payment.company_id or self.env.company
            # Determinar los tipos de diario permitidos según el tipo de transacción
            journal_types = ['bank', 'cash', 'credit']
            if payment.type_mov == 'other':
                journal_types = ['general']
            # if payment.type_mov == 'advance':
            #     journal_types = ['advance']
            if payment.type_mov == 'cross':
                journal_types = ['cross']
            domain = [
                *self.env['account.journal']._check_company_domain(company),
                ('type', 'in', journal_types),
                ('company_id', '=', company.id),
            ]

            if any(journal_type not in ['bank', 'cash', 'credit'] for journal_type in journal_types):
                payment_type_inverso = 'outbound' if self.payment_type=='inbound' else 'inbound'
                domain.append(('payment_type', '!=', payment_type_inverso))
            payment.journal_id = self.env['account.journal'].search(domain, limit=1)


    @api.constrains('journal_id', 'type_mov')
    def _check_journal_type(self):
        for payment in self:
            if payment.type_mov == 'advance' and payment.journal_id.type != 'advance':
                raise ValidationError("Para transacciones de tipo 'Anticipo', seleccione un diario de tipo 'Anticipo'.")
            elif payment.type_mov == 'cross' and payment.journal_id.type != 'cross':
                raise ValidationError("Para transacciones de tipo 'Cruce de Cartera', seleccione un diario de tipo 'Cruce de Cartera'.")


    @api.depends('company_id','payment_type','type_mov')
    def _compute_available_journal_ids(self):
        """
        Get all journals having at least one payment method for inbound/outbound depending on the payment_type.
        """
        # journal_types = []
        journal_types = ['bank', 'cash', 'credit']
        if self.type_mov == 'other':
            journal_types = ['general']
        # if self.type_mov == 'advance':
        #     journal_types = ['advance']
        if self.type_mov == 'cross':
            journal_types = ['cross']
        domain = [
            '|',
            ('company_id', 'parent_of', self.env.company.id),
            ('company_id', 'child_of', self.env.company.id),
            ('type', 'in', journal_types),
            ]
        # Agregar la condición de `payment_type` solo si es un diario de tipo 'bank', 'cash', o 'credit'
        payment_type_inverso = 'outbound' if self.payment_type=='inbound' else 'inbound'
        if any(journal_type not in ['bank', 'cash', 'credit'] for journal_type in journal_types):
            domain.append(('payment_type', '!=', payment_type_inverso))
        journals = self.env['account.journal'].search(domain)
        for pay in self:
            # Verificar si `journal_types` contiene algún valor de 'bank', 'cash' o 'credit'
            if any(journal_type in ['bank', 'cash', 'credit'] for journal_type in journal_types):
                # Filtrar según el tipo de pago (inbound/outbound)
                if pay.payment_type == 'inbound':
                    pay.available_journal_ids = journals.filtered('inbound_payment_method_line_ids')
                else:
                    pay.available_journal_ids = journals.filtered('outbound_payment_method_line_ids')
            else:
                pay.available_journal_ids = journals
