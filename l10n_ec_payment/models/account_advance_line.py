# -*- coding: utf-8 -*-
from odoo import models, fields, api, _, Command
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare, float_is_zero


class AccountAdvanceLine(models.Model):
    _name = 'account.advance.line'
    _description = 'Formas de Pago del Anticipo'
    _order = 'sequence, id'

    # Campos relacionados con el anticipo
    advance_id = fields.Many2one('account.advance', string='Anticipo', required=True, ondelete='cascade')
    advance_type = fields.Selection(related='advance_id.advance_type', store=True, readonly=True)
    related_payment_type = fields.Selection(related='advance_id.advance_type', string='Tipo de Pago Relacionado')
    state = fields.Selection(related='advance_id.state', string='Estado', store=True)
    
    # Campos relacionados con el socio
    partner_id = fields.Many2one(related='advance_id.partner_id', store=True, readonly=True)
    partner_type = fields.Selection(related='advance_id.partner_type', store=True, readonly=True)
    company_id = fields.Many2one(related='advance_id.company_id', store=True, readonly=True)
 
    move_id = fields.Many2one(
        comodel_name='account.move',
        string='Asiento',
        index=True,
        copy=False,
        check_company=True)
        
    # Campos de configuración general
    sequence = fields.Integer(default=10)
    currency_id = fields.Many2one('res.currency', related='advance_id.currency_id')
    amount = fields.Monetary(string='Monto', required=True, currency_field='currency_id')
    
    # Campos de método de diario y pago
    journal_id = fields.Many2one(
        string="Diario",
        comodel_name='account.journal',
        compute='_compute_journal_id', store=True, readonly=False,
        check_company=True,
        index=False,  # covered by account_advance_journal_id_company_id_idx
        required=True,
    )
    available_journal_ids = fields.Many2many(
        comodel_name='account.journal',
        compute='_compute_available_journal_ids'
    )
  
    origin_account_id = fields.Many2one(
        comodel_name='account.account',
        string="Cuenta Origen",
        store=True,
        index='btree_not_null',
        compute='_compute_origin_account_id',
        check_company=True)
    
    destination_account_id = fields.Many2one(
        comodel_name='account.account',
        string='Cuenta Destino',
        store=True,
        compute='_compute_destination_account_id',
        domain="[('account_type', 'in', ('asset_receivable', 'liability_payable'))]",
        check_company=True)

    
    # Campos de método de pago
    advance_method_line_id = fields.Many2one('account.payment.method.line', string='Linea Metodo',
        readonly=False, store=True, copy=False,
        compute='_compute_advance_method_line_id',
        domain="[('id', 'in', available_advance_method_line_ids)]"
    )
    available_advance_method_line_ids = fields.Many2many('account.payment.method.line',
        compute='_compute_advance_method_line_fields')
    advance_method_id = fields.Many2one(
        related='advance_method_line_id.payment_method_id',
        string="Metodo",
        store=True
    )
    advance_method_code = fields.Char(
        related='advance_method_line_id.code',
        store=True)
    
    # Campos de cuenta bancaria
    available_partner_bank_ids = fields.Many2many(
        comodel_name='res.partner.bank',
        compute='_compute_available_partner_bank_ids',
    )
    partner_bank_id = fields.Many2one('res.partner.bank', string="Cuenta Bancaria",
        readonly=False, store=True, 
        compute='_compute_partner_bank_id',
        domain="[('id', 'in', available_partner_bank_ids)]",
        check_company=True,
        ondelete='restrict',
    )
    show_partner_bank_account = fields.Boolean(
        compute='_compute_show_require_partner_bank')
    require_partner_bank_account = fields.Boolean(
        compute='_compute_show_require_partner_bank')
    
    # Campos de documentos
    nro_document = fields.Char(string="Numero Documento")
    date_document = fields.Date(string="Fecha Documento", default=fields.Date.context_today, required=True)
    
    # Campos para cheques
    check_due_date = fields.Date(string='Fecha de Cobro')
    show_check_due_date = fields.Boolean(
        compute='_compute_show_require_partner_bank')
    require_check_due_date = fields.Boolean(
        compute='_compute_show_require_partner_bank')
    
    # Campos para tarjetas de crédito/débito
    card_brand_id = fields.Many2one('account.credit.card.brand', string='Marca de Tarjeta')
    card_deadline_id = fields.Many2one('account.credit.card.deadline', string='Plazo de Tarjeta')
    show_credit_card = fields.Boolean(
        compute='_compute_show_require_partner_bank')
    require_credit_card = fields.Boolean(
        compute='_compute_show_require_partner_bank')

    show_nro_document = fields.Boolean(compute='_compute_show_require_partner_bank')
    show_date_document = fields.Boolean(compute='_compute_show_require_partner_bank')

    lote_id = fields.Many2one('account.card.lote', string='Lote',tracking=True)


    # === Métodos de configuración ===
    @api.model
    def _get_method_codes_using_bank_account(self):
        return ['check_printing', 'transf', 'card_debit', 'bank_debit']

    @api.model
    def _get_method_codes_needing_bank_account(self):
        return ['check_printing', 'transf', 'card_debit', 'bank_debit']
    
    @api.model
    def _get_method_codes_using_check_due_date(self):
        # Solo mostrar fecha de vencimiento para estos métodos específicos
        return ['check_printing', 'deposit_cheque']

    @api.model
    def _get_method_codes_needing_check_due_date(self):
        # Solo requerir fecha de vencimiento para estos métodos específicos
        return ['check_printing', 'deposit_cheque']

    @api.model
    def _get_method_codes_using_credit_card(self):
        # Solo mostrar fecha de vencimiento para estos métodos específicos
        return ['card_credit', 'card_debit']

    @api.model
    def _get_method_codes_needing_credit_card(self):
        # Solo requerir fecha de vencimiento para estos métodos específicos
        return ['card_credit', 'card_debit']
    
    def _get_advance_method_codes_to_exclude(self):
        # can be overriden to exclude advance methods based on the advance characteristics
        self.ensure_one()
        return []

    @api.depends('advance_method_line_id')
    def _compute_origin_account_id(self):
        for pay in self:
            pay.origin_account_id = pay.journal_id.default_account_id

    @api.depends('journal_id', 'partner_id', 'partner_type')
    def _compute_destination_account_id(self):
        self.destination_account_id = False
        
        for pay in self:
            if pay.partner_type == 'customer':
                # Receive money from invoice or send money to refund it.
                if pay.partner_id:
                    pay.destination_account_id = pay.company_id.l10n_ec_payment_advance_customer_journal_id.default_account_id
                else:
                    pay.destination_account_id = self.env['account.account'].with_company(pay.company_id).search([
                        *self.env['account.account']._check_company_domain(pay.company_id),
                        ('account_type', 'in', ['liability_current','liability_payable']),
                        ('deprecated', '=', False),
                    ], limit=1)
            elif pay.partner_type == 'supplier':
                # Send money to pay a bill or receive money to refund it.
                if pay.partner_id:
                    pay.destination_account_id = pay.company_id.l10n_ec_payment_advance_vendor_journal_id.default_account_id
                else:
                    pay.destination_account_id = self.env['account.account'].with_company(pay.company_id).search([
                        *self.env['account.account']._check_company_domain(pay.company_id),
                        ('account_type', '=', 'asset_prepayments'),
                        ('deprecated', '=', False),
                    ], limit=1)
    # === Campos computados ===
    @api.depends('company_id')
    def _compute_journal_id(self):
        for advance in self:
            company = advance.company_id or self.env.company
            advance.journal_id = self.env['account.journal'].search([
                *self.env['account.journal']._check_company_domain(company),
                ('type', 'in', ['bank', 'cash', 'credit']),
            ], limit=1)

    @api.depends('advance_type')
    def _compute_available_journal_ids(self):
        """
        Get all journals having at least one advance method for inbound/outbound depending on the advance_type.
        """
        journals = self.env['account.journal'].search([
            '|',
            ('company_id', 'parent_of', self.env.company.id),
            ('company_id', 'child_of', self.env.company.id),
            ('type', 'in', ('bank', 'cash', 'credit')),
        ])
        for pay in self:
            if pay.advance_type == 'inbound':
                pay.available_journal_ids = journals.filtered('inbound_payment_method_line_ids')
            else:
                pay.available_journal_ids = journals.filtered('outbound_payment_method_line_ids')

    @api.depends('advance_type', 'journal_id', 'currency_id')
    def _compute_advance_method_line_fields(self):
        for pay in self:
            pay.available_advance_method_line_ids = pay.journal_id._get_available_payment_method_lines(pay.advance_type)
            to_exclude = pay._get_advance_method_codes_to_exclude()
            if to_exclude:
                pay.available_advance_method_line_ids = pay.available_advance_method_line_ids.filtered(lambda x: x.code not in to_exclude)

    @api.depends('available_advance_method_line_ids')
    def _compute_advance_method_line_id(self):
        ''' Compute the 'advance_method_line_id' field.
        This field is not computed in '_compute_advance_method_line_fields' because it's a stored editable one.
        '''
        for pay in self:
            available_advance_method_lines = pay.available_advance_method_line_ids
            inbound_advance_method = pay.partner_id.property_inbound_payment_method_line_id
            outbound_advance_method = pay.partner_id.property_outbound_payment_method_line_id
            if pay.advance_type == 'inbound' and inbound_advance_method.id in available_advance_method_lines.ids:
                pay.advance_method_line_id = inbound_advance_method
            elif pay.advance_type == 'outbound' and outbound_advance_method.id in available_advance_method_lines.ids:
                pay.advance_method_line_id = outbound_advance_method
            elif pay.advance_method_line_id.id in available_advance_method_lines.ids:
                pay.advance_method_line_id = pay.advance_method_line_id
            elif available_advance_method_lines:
                pay.advance_method_line_id = available_advance_method_lines[0]._origin
            else:
                pay.advance_method_line_id = False

    @api.depends('partner_id', 'company_id', 'advance_type')
    def _compute_available_partner_bank_ids(self):
        for pay in self:
            if pay.advance_type == 'inbound':
                pay.available_partner_bank_ids = pay.journal_id.bank_account_id
            else:
                pay.available_partner_bank_ids = pay.partner_id.bank_ids\
                        .filtered(lambda x: x.company_id.id in (False, pay.company_id.id))._origin

    @api.depends('available_partner_bank_ids', 'journal_id')
    def _compute_partner_bank_id(self):
        ''' The default partner_bank_id will be the first available on the partner. '''
        for pay in self:
            if pay.partner_bank_id not in pay.available_partner_bank_ids:
                pay.partner_bank_id = pay.available_partner_bank_ids[:1]._origin


    @api.depends('advance_method_code', 'advance_type', 'state', 'journal_id.type')
    def _compute_show_require_partner_bank(self):
        for advance in self:
            code = advance.advance_method_code
            atype = advance.advance_type
            journal_cash = advance.journal_id.type == 'cash'

            # Cuenta bancaria
            advance.show_partner_bank_account = not journal_cash and code in self._get_method_codes_using_bank_account()
            advance.require_partner_bank_account = advance.state == 'draft' and code in self._get_method_codes_needing_bank_account()

            # Cheques
            advance.show_check_due_date = code in self._get_method_codes_using_check_due_date()
            advance.require_check_due_date = advance.state == 'draft' and code in self._get_method_codes_needing_check_due_date()

            # Tarjeta
            advance.show_credit_card = code in self._get_method_codes_using_credit_card()
            advance.require_credit_card = advance.state == 'draft' and code in self._get_method_codes_needing_credit_card()

            # nro_document y date_document visibles excepto método "manual"
            advance.show_nro_document = code != 'manual'
            advance.show_date_document = code != 'manual'

    @api.onchange('advance_method_line_id')
    def _onchange_advance_method_line_id_labels(self):
        for advance in self:    
            code = advance.advance_method_line_id.code
            print(code)
            # Etiquetas dinámicas
            if code in ['check_printing', 'deposit_cheque']:
                advance.label_nro_document = 'Número del Cheque'
                advance.label_date_document = 'Fecha del Cheque'
            elif code == 'transf':
                advance.label_nro_document = 'Referencia de Transferencia'
                advance.label_date_document = 'Fecha de Transferencia'
            elif code in ['card_credit', 'card_debit']:
                advance.label_nro_document = 'Número de Voucher'
                advance.label_date_document = 'Fecha del Voucher'
            elif code == 'bank_debit':
                advance.label_nro_document = 'Referencia Débito Bancario'
                advance.label_date_document = 'Fecha del Débito'
            else:
                advance.label_nro_document = 'Número Documento'
                advance.label_date_document = 'Fecha Documento'

    # @api.depends('advance_method_code')
    # def _compute_show_require_partner_bank(self):
    #     """ Computes if the destination bank account must be displayed in the advance form view. By default, it
    #     won't be displayed but some modules might change that, depending on the advance type."""
    #     for advance in self:
    #         # Para cuenta bancaria
    #         if advance.journal_id.type == 'cash':
    #             advance.show_partner_bank_account = False
    #         else:
    #             advance.show_partner_bank_account = advance.advance_method_code in self._get_method_codes_using_bank_account()
    #         advance.require_partner_bank_account = advance.state == 'draft' and advance.advance_method_code in self._get_method_codes_needing_bank_account()
            
    #         # Para fecha de vencimiento del cheque - cálculo separado
    #         advance.show_check_due_date = advance.advance_method_code in self._get_method_codes_using_check_due_date()
    #         advance.require_check_due_date = advance.state == 'draft' and advance.advance_method_code in self._get_method_codes_needing_check_due_date()
    #         advance.show_credit_card = advance.advance_method_code in self._get_method_codes_using_credit_card()
    #         advance.require_credit_card = advance.state == 'draft' and advance.advance_method_code in self._get_method_codes_needing_credit_card()

    # === Restricciones ===
    @api.constrains('amount')
    def _check_amount(self):
        for method in self:
            if method.amount <= 0:
                raise ValidationError(_('El monto debe ser mayor que cero.'))

    # === Métodos para la creación y gestión del asiento contable ===
    def _get_valid_advance_account_types(self):
        ''' Helper usado para definir los tipos de cuenta válidos para un anticipo. '''
        return ['asset_receivable', 'liability_payable']

    def _seek_for_lines(self):
        ''' Helper para clasificar las líneas del asiento entre:
        - Las líneas que usan la cuenta de liquidez temporal.
        - Las líneas que usan la cuenta de contrapartida.
        - Las líneas que son de ajuste.
        :return: (liquidity_lines, counterpart_lines, writeoff_lines)
        '''
        self.ensure_one()

        # liquidity_lines, counterpart_lines, writeoff_lines
        lines = [self.env['account.move.line'] for _dummy in range(3)]
        valid_account_types = self._get_valid_advance_account_types()
        for line in self.move_id.line_ids:
            if line.account_id in self._get_valid_liquidity_accounts():
                lines[0] += line  # liquidity_lines
            elif line.account_id.account_type in valid_account_types or line.account_id == line.company_id.transfer_account_id:
                lines[1] += line  # counterpart_lines
            else:
                lines[2] += line  # writeoff_lines

        # En algunos casos, no hay línea de liquidez o contrapartida (después de cambiar una cuenta pendiente en el diario, por ejemplo)
        # En ese caso, y si hay una línea de ajuste, tomamos esta línea y la establecemos como línea de liquidez/contrapartida
        if len(lines[2]) == 1:
            for i in (0, 1):
                if not lines[i]:
                    lines[i] = lines[2]
                    lines[2] -= lines[2]

        return lines

    def _get_valid_liquidity_accounts(self):
        return (
            self.journal_id.default_account_id |
            self.advance_method_line_id.payment_account_id |
            self.journal_id.inbound_payment_method_line_ids.payment_account_id |
            self.journal_id.outbound_payment_method_line_ids.payment_account_id
        )

    def _get_aml_default_display_name_list(self):
        """ Hook que permite valores personalizados al construir la etiqueta predeterminada para las líneas del asiento.
        :return: Una lista de términos para concatenar. Ejemplo:
            [
                ('label', "Tarjeta de Greg"),
                ('sep', ": "),
                ('nro_document', "Nueva Computadora"),
            ]
        """
        self.ensure_one()
        label = self.advance_method_line_id.name if self.advance_method_line_id else _("Sin Método de Anticipo")

        if self.nro_document:
            return [
                ('label', label),
                ('sep', ": "),
                ('nro_document', self.nro_document),
            ]
        return [
            ('label', label),
        ]

    def _prepare_move_line_default_vals(self, write_off_line_vals=None, force_balance=None):
        ''' Prepara el diccionario para crear las líneas de asiento por defecto para este método de pago.
        :param write_off_line_vals: Lista opcional de diccionarios para crear una línea de ajuste.
        :param force_balance: Saldo opcional forzado.
        :return: Una lista de diccionarios para la creación de líneas de asiento.
        '''
        self.ensure_one()
        write_off_line_vals = write_off_line_vals or []

        if not self.origin_account_id:
            raise UserError(_(
                "No se puede crear un nuevo pago sin una cuenta de anticipos pendientes configurada en la compañía o en el método de pago %(advance_method)s en el diario %(journal)s.",
                advance_method=self.advance_method_line_id.name, journal=self.journal_id.display_name))

        # Calcular montos
        write_off_line_vals_list = write_off_line_vals or []
        write_off_amount_currency = sum(x.get('amount_currency', 0) for x in write_off_line_vals_list)
        write_off_balance = sum(x.get('balance', 0) for x in write_off_line_vals_list)

        if self.advance_type == 'inbound':
            # Recibir dinero
            liquidity_amount_currency = self.amount
        elif self.advance_type == 'outbound':
            # Enviar dinero
            liquidity_amount_currency = -self.amount
        else:
            liquidity_amount_currency = 0.0

        if not write_off_line_vals and force_balance is not None:
            sign = 1 if liquidity_amount_currency > 0 else -1
            liquidity_balance = sign * abs(force_balance)
        else:
            liquidity_balance = self.currency_id._convert(
                liquidity_amount_currency,
                self.company_id.currency_id,
                self.company_id,
                self.date_document,
            )
        counterpart_amount_currency = -liquidity_amount_currency - write_off_amount_currency
        counterpart_balance = -liquidity_balance - write_off_balance
        currency_id = self.currency_id.id

        # Calcular una etiqueta predeterminada para las líneas de asiento
        liquidity_line_name = ''.join(x[1] for x in self._get_aml_default_display_name_list())
        counterpart_line_name = ''.join(x[1] for x in self._get_aml_default_display_name_list())

        line_vals_list = [
            # Línea de liquidez
            {
                'name': liquidity_line_name,
                'date_maturity': self.date_document,
                'amount_currency': liquidity_amount_currency,
                'currency_id': currency_id,
                'debit': liquidity_balance if liquidity_balance > 0.0 else 0.0,
                'credit': -liquidity_balance if liquidity_balance < 0.0 else 0.0,
                'partner_id': self.partner_id.id,
                'account_id': self.origin_account_id.id,
            },
            # Cuenta por cobrar / por pagar
            {
                'name': counterpart_line_name,
                'date_maturity': self.date_document,
                'amount_currency': counterpart_amount_currency,
                'currency_id': currency_id,
                'debit': counterpart_balance if counterpart_balance > 0.0 else 0.0,
                'credit': -counterpart_balance if counterpart_balance < 0.0 else 0.0,
                'partner_id': self.partner_id.id,
                'account_id': self.destination_account_id.id,
            },
        ]
        return line_vals_list + write_off_line_vals_list

    def _generate_journal_entry(self, write_off_line_vals=None, force_balance=None, line_ids=None):
        """Genera el asiento contable para este método de pago del anticipo"""
        need_move = self.filtered(lambda p: not p.move_id and p.origin_account_id)
        
        move_vals = []
        for pay in need_move:
            move_vals.append({
                'move_type': 'entry',
                'ref': pay.nro_document or '',
                'date': pay.date_document,
                'journal_id': pay.journal_id.id,
                'company_id': pay.company_id.id,
                'partner_id': pay.partner_id.id,
                'currency_id': pay.currency_id.id,
                'partner_bank_id': pay.partner_bank_id.id if hasattr(pay, 'partner_bank_id') else False,
                'line_ids': line_ids or [
                    Command.create(line_vals)
                    for line_vals in pay._prepare_move_line_default_vals(
                        write_off_line_vals=write_off_line_vals,
                        force_balance=force_balance,
                    )
                ],
                'origin_advance_id': pay.advance_id.id,
            })
        moves = self.env['account.move'].create(move_vals)
        for pay, move in zip(need_move, moves):
            pay.write({'move_id': move.id})
            
        # En lugar de llamar a un método inexistente, simplemente invalidamos el caché 
        # para que los campos computados se actualicen
        if moves and self.mapped('advance_id'):
            self.mapped('advance_id').invalidate_recordset(['move_ids', 'move_count'])

    def _synchronize_to_moves(self, changed_fields):
        '''
            Actualiza el asiento contable (account.move) respecto a los campos modificados.
            :param changed_fields: Lista de campos modificados.
        '''
        if not any(field_name in changed_fields for field_name in self._get_trigger_fields_to_synchronize()):
            return

        for pay in self:
            if not pay.move_id:
                continue
                
            liquidity_lines, counterpart_lines, writeoff_lines = pay._seek_for_lines()
            # Asegurarse de preservar el monto de ajuste
            write_off_line_vals = []
            if liquidity_lines and counterpart_lines and writeoff_lines:
                write_off_line_vals.append({
                    'name': writeoff_lines[0].name,
                    'account_id': writeoff_lines[0].account_id.id,
                    'partner_id': writeoff_lines[0].partner_id.id,
                    'currency_id': writeoff_lines[0].currency_id.id,
                    'amount_currency': sum(writeoff_lines.mapped('amount_currency')),
                    'balance': sum(writeoff_lines.mapped('balance')),
                })
            line_vals_list = pay._prepare_move_line_default_vals(write_off_line_vals=write_off_line_vals)
            line_ids_commands = [
                Command.update(liquidity_lines.id, line_vals_list[0]) if liquidity_lines else Command.create(line_vals_list[0]),
                Command.update(counterpart_lines.id, line_vals_list[1]) if counterpart_lines else Command.create(line_vals_list[1])
            ]
            for line in writeoff_lines:
                line_ids_commands.append((2, line.id))
            for extra_line_vals in line_vals_list[2:]:
                line_ids_commands.append((0, 0, extra_line_vals))
                
            # Actualiza las líneas de asiento existentes
            pay.move_id.with_context(skip_invoice_sync=True).write({
                'partner_id': pay.partner_id.id,
                'currency_id': pay.currency_id.id,
                'partner_bank_id': pay.partner_bank_id.id if hasattr(pay, 'partner_bank_id') else False,
                'line_ids': line_ids_commands,
            })

    def _get_trigger_fields_to_synchronize(self):
        """Campos que al modificarse deben sincronizarse con el asiento contable"""
        return (
            'date_document', 'amount', 'advance_type', 'partner_type', 'nro_document',
            'currency_id', 'partner_id', 'destination_account_id', 'partner_bank_id', 'journal_id'
        )
        
    def action_post(self):
        """Publica el método de pago del anticipo, generando el asiento contable"""
        for method in self:
            # Validaciones
            if method.require_partner_bank_account and not method.partner_bank_id:
                raise UserError(_(
                    "Para registrar pagos con %(method_name)s, debe especificar una cuenta bancaria.",
                    method_name=method.advance_method_line_id.name,
                ))
            if method.require_check_due_date:
                if not method.check_due_date:
                    raise UserError(_('Debe ingresar la fecha de cobro del cheque.'))
                if method.nro_document:
                    if len(method.nro_document) < 1:
                        raise UserError('El Numero de Documento (Cheque) debe contener al menos 1 caracteres')
                else:
                    if method.advance_type=='inbound':
                        raise UserError('El Numero de Documento (Cheque) es obligatorio')
                        
            # Generar asiento si no existe
            if not method.move_id:
                method._generate_journal_entry()
                
            # Publicar el asiento
            if method.move_id.state == 'draft':
                method.move_id.action_post()
                
        return True
        
    def action_draft(self):
        """Regresa el método de pago al estado borrador"""
        for method in self:
            if method.move_id and method.move_id.state != 'draft':
                method.move_id.button_draft()
        return True

    def write(self, vals):
        """Sobrescribe el método write para sincronizar campos con los asientos contables"""
        if vals.get('state') == 'posted' and not vals.get('move_id'):
            self.filtered(lambda p: not p.move_id)._generate_journal_entry()
            self.move_id.action_post()

        result = super().write(vals)
        
        # Identificar qué campos han cambiado y podrían requerir sincronización
        fields_to_sync = set(vals.keys()) & set(self._get_trigger_fields_to_synchronize())
        if fields_to_sync:
            self._synchronize_to_moves(fields_to_sync)
            
        return result
        
    def unlink(self):
        """Elimina el método de pago y su asiento relacionado"""
        # Primero pasar a borrador los asientos que no estén en ese estado
        draft_moves = self.mapped('move_id').filtered(lambda m: m.state != 'draft')
        if draft_moves:
            draft_moves.button_draft()
        
        # Eliminar los asientos
        self.mapped('move_id').unlink()
        
        return super(AccountAdvanceLine, self).unlink()
