# -*- coding: utf-8 -*-
from odoo import models, fields, api, _, Command
from odoo.exceptions import UserError, ValidationError
from odoo.tools.misc import format_date, formatLang
from odoo.tools import create_index
from odoo.tools import SQL


class AccountPayment(models.Model):
    _name = 'account.advance'

    _inherit = ['mail.thread.main.attachment', 'mail.activity.mixin']
    _description = "Advances"
    _order = "date desc, name desc"
    _check_company_auto = True


    # == Business fields ==
    name = fields.Char(string="Numero", compute='_compute_name', store=True)
    date = fields.Date(string="Fecha", default=fields.Date.context_today, required=True, tracking=True)
    date_estimated = fields.Date(string="Fecha Estimada", default=fields.Date.context_today, required=True, tracking=True)

    move_id = fields.Many2one(
        comodel_name='account.move',
        string='Asiento',
        index=True,
        copy=False,
        check_company=True)
    journal_id = fields.Many2one(
        string="Diario",
        comodel_name='account.journal',
        compute='_compute_journal_id', store=True, readonly=False, precompute=True,
        check_company=True,
        index=False,  # covered by account_advance_journal_id_company_id_idx
        required=True,
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        compute='_compute_company_id', store=True, readonly=False, precompute=True,
        index=False,  # covered by account_advance_journal_id_company_id_idx
        required=True
    )
    state = fields.Selection(
        selection=[
            ('draft', "Borrador"),
            ('in_process', "En Proceso"),
            ('paid', "Pagado"),
            ('canceled', "Cancelado"),
            ('rejected', "Rechazado"),
        ],
        required=True,
        default='draft',
        compute='_compute_state', store=True, readonly=False,
        copy=False,
    )
    is_sent = fields.Boolean(string="Esta Enviado", readonly=True, copy=False)
    available_partner_bank_ids = fields.Many2many(
        comodel_name='res.partner.bank',
        compute='_compute_available_partner_bank_ids',
    )
    partner_bank_id = fields.Many2one('res.partner.bank', string="Cuenta Bancaria",
        readonly=False, store=True, tracking=True,
        compute='_compute_partner_bank_id',
        domain="[('id', 'in', available_partner_bank_ids)]",
        check_company=True,
        ondelete='restrict',
    )


    # == Advance methods fields ==
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
        tracking=True,
        store=True
    )
    available_journal_ids = fields.Many2many(
        comodel_name='account.journal',
        compute='_compute_available_journal_ids'
    )

    amount = fields.Monetary(string="Monto", currency_field='currency_id')
    amoount_used = fields.Monetary(string="Monto Usado", currency_field='currency_id')
    amoount_available = fields.Monetary(string="Monto Disponible", currency_field='currency_id')
    amoount_returned = fields.Monetary(string="Monto Devuelto", currency_field='currency_id')

    advance_type = fields.Selection([
        ('outbound', 'Enviar'),
        ('inbound', 'Recibir'),
    ], string='Tipo de Anticipo', default='inbound', required=True, tracking=True)
    partner_type = fields.Selection([
        ('customer', 'Cliente'),
        ('supplier', 'Acreedor'),
    ], default='customer', tracking=True, required=True)
    nro_document = fields.Char(string="Numero Documento", tracking=True)
    date_document = fields.Date(string="Fecha Documento", default=fields.Date.context_today, required=True, tracking=True)

    reference = fields.Char(string="Glosa", copy=False, tracking=True)
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        compute='_compute_currency_id', store=True, readonly=False, precompute=True,
        help="The advance's currency.")
    company_currency_id = fields.Many2one(string="Company Currency", related='company_id.currency_id')
    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string="Customer/Vendor",
        store=True, readonly=False, ondelete='restrict',
        compute='_compute_partner_id',
        inverse='_inverse_partner_id',
        domain="['|', ('parent_id','=', False), ('is_company','=', True)]",
        tracking=True,
        check_company=True)
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


    payment_ids = fields.One2many('account.payment', 'advance_id', string='Pagos')


    # == Display purpose fields ==
    advance_method_code = fields.Char(
        related='advance_method_line_id.code')
    advance_receipt_title = fields.Char(
        compute='_compute_advance_receipt_title'
    )

    need_cancel_request = fields.Boolean(related='move_id.need_cancel_request')
    # used to know whether the field `partner_bank_id` needs to be displayed or not in the advances form views
    show_partner_bank_account = fields.Boolean(
        compute='_compute_show_require_partner_bank')
    # used to know whether the field `partner_bank_id` needs to be required or not in the advances form views
    require_partner_bank_account = fields.Boolean(
        compute='_compute_show_require_partner_bank')
    country_code = fields.Char(related='company_id.account_fiscal_country_id.code')
    amount_signed = fields.Monetary(
        currency_field='currency_id', compute='_compute_amount_signed', tracking=True,
        help='Negative value of amount field if advance_type is outbound')
    amount_company_currency_signed = fields.Monetary(
        currency_field='company_currency_id', compute='_compute_amount_company_currency_signed', store=True)
    # used to get and display duplicate move warning if partner, amount and date match existing advances
    attachment_ids = fields.One2many('ir.attachment', 'res_id', string='Attachments')

    _sql_constraints = [
        (
            'check_amount_not_negative',
            'CHECK(amount >= 0.0)',
            "The advance amount cannot be negative.",
        ),
    ]

    def init(self):
        super().init()
        create_index(
            self.env.cr,
            indexname='account_advance_journal_id_company_id_idx',
            tablename='account_advance',
            expressions=['journal_id', 'company_id']
        )


    # -------------------------------------------------------------------------
    # HELPERS
    # -------------------------------------------------------------------------

    @api.model
    def _get_valid_advance_account_types(self):
        return ['asset_receivable', 'liability_payable']

    def _seek_for_lines(self):
        ''' Helper used to dispatch the journal items between:
        - The lines using the temporary liquidity account.
        - The lines using the counterpart account.
        - The lines being the write-off lines.
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

        # In some case, there is no liquidity or counterpart line (after changing an outstanding account on the journal for example)
        # In that case, and if there is one writeoff line, we take this line and set it as liquidity/counterpart line
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
        """ Hook allowing custom values when constructing the default label to set on the journal items.

        :return: A list of terms to concatenate all together. E.g.
            [
                ('label', "Greg's Card"),
                ('sep', ": "),
                ('nro_document', "New Computer"),
            ]
        """
        self.ensure_one()
        label = self.advance_method_line_id.name if self.advance_method_line_id else _("No Advance Method")

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
        ''' Prepare the dictionary to create the default account.move.lines for the current advance.
        :param write_off_line_vals: Optional list of dictionaries to create a write-off account.move.line easily containing:
            * amount:       The amount to be added to the counterpart amount.
            * name:         The label to set on the line.
            * account_id:   The account on which create the write-off.
        :param force_balance: Optional balance.
        :return: A list of python dictionary to be passed to the account.move.line's 'create' method.
        '''
        self.ensure_one()
        write_off_line_vals = write_off_line_vals or []

        if not self.origin_account_id:
            raise UserError(_(
                "You can't create a new advance without an outstanding advances/receipts account set either on the company or the %(advance_method)s advance method in the %(journal)s journal.",
                advance_method=self.advance_method_line_id.name, journal=self.journal_id.display_name))

        # Compute amounts.
        write_off_line_vals_list = write_off_line_vals or []
        write_off_amount_currency = sum(x['amount_currency'] for x in write_off_line_vals_list)
        write_off_balance = sum(x['balance'] for x in write_off_line_vals_list)

        if self.advance_type == 'inbound':
            # Receive money.
            liquidity_amount_currency = self.amount
        elif self.advance_type == 'outbound':
            # Send money.
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
                self.date,
            )
        counterpart_amount_currency = -liquidity_amount_currency - write_off_amount_currency
        counterpart_balance = -liquidity_balance - write_off_balance
        currency_id = self.currency_id.id

        # Compute a default label to set on the journal items.
        liquidity_line_name = ''.join(x[1] for x in self._get_aml_default_display_name_list())
        counterpart_line_name = ''.join(x[1] for x in self._get_aml_default_display_name_list())

        line_vals_list = [
            # Liquidity line.
            {
                'name': liquidity_line_name,
                'date_maturity': self.date,
                'amount_currency': liquidity_amount_currency,
                'currency_id': currency_id,
                'debit': liquidity_balance if liquidity_balance > 0.0 else 0.0,
                'credit': -liquidity_balance if liquidity_balance < 0.0 else 0.0,
                'partner_id': self.partner_id.id,
                'account_id': self.origin_account_id.id,
            },
            # Receivable / Payable.
            {
                'name': counterpart_line_name,
                'date_maturity': self.date,
                'amount_currency': counterpart_amount_currency,
                'currency_id': currency_id,
                'debit': counterpart_balance if counterpart_balance > 0.0 else 0.0,
                'credit': -counterpart_balance if counterpart_balance < 0.0 else 0.0,
                'partner_id': self.partner_id.id,
                'account_id': self.destination_account_id.id,
            },
        ]
        return line_vals_list + write_off_line_vals_list

    # -------------------------------------------------------------------------
    # COMPUTE METHODS
    # -------------------------------------------------------------------------

    @api.depends('move_id.name', 'state')
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

    @api.depends('company_id')
    def _compute_journal_id(self):
        for advance in self:
            company = self.company_id or self.env.company
            advance.journal_id = self.env['account.journal'].search([
                *self.env['account.journal']._check_company_domain(company),
                ('type', 'in', ['bank', 'cash', 'credit']),
            ], limit=1)

    @api.depends('journal_id')
    def _compute_company_id(self):
        for advance in self:
            if advance.journal_id.company_id not in advance.company_id.parent_ids:
                advance.company_id = (advance.journal_id.company_id or self.env.company)._accessible_branches()[:1]

    @api.depends('payment_ids.state')
    def _compute_state(self):
        for advance in self:
            if not advance.state:
                advance.state = 'draft'
            if (
                advance.payment_ids
                and all(pay.state == 'paid' for pay in advance.payment_ids)
            ):
                advance.state = 'paid'


    @api.model
    def _get_method_codes_using_bank_account(self):
        return ['manual']

    @api.model
    def _get_method_codes_needing_bank_account(self):
        return []

    @api.depends('advance_method_code')
    def _compute_show_require_partner_bank(self):
        """ Computes if the destination bank account must be displayed in the advance form view. By default, it
        won't be displayed but some modules might change that, depending on the advance type."""
        for advance in self:
            if advance.journal_id.type == 'cash':
                advance.show_partner_bank_account = False
            else:
                advance.show_partner_bank_account = advance.advance_method_code in self._get_method_codes_using_bank_account()
            advance.require_partner_bank_account = advance.state == 'draft' and advance.advance_method_code in self._get_method_codes_needing_bank_account()

    @api.depends('move_id.amount_total_signed', 'amount', 'advance_type', 'currency_id', 'date', 'company_id', 'company_currency_id')
    def _compute_amount_company_currency_signed(self):
        for advance in self:
            if advance.move_id:
                liquidity_lines = advance._seek_for_lines()[0]
                advance.amount_company_currency_signed = sum(liquidity_lines.mapped('balance'))
            else:
                advance.amount_company_currency_signed = advance.currency_id._convert(
                    from_amount=advance.amount,
                    to_currency=advance.company_currency_id,
                    company=advance.company_id,
                    date=advance.date,
                )

    @api.depends('amount', 'advance_type')
    def _compute_amount_signed(self):
        for advance in self:
            if advance.advance_type == 'outbound':
                advance.amount_signed = -advance.amount
            else:
                advance.amount_signed = advance.amount

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

    @api.depends('advance_type', 'journal_id', 'currency_id')
    def _compute_advance_method_line_fields(self):
        for pay in self:
            pay.available_advance_method_line_ids = pay.journal_id._get_available_payment_method_lines(pay.advance_type)
            to_exclude = pay._get_advance_method_codes_to_exclude()
            if to_exclude:
                pay.available_advance_method_line_ids = pay.available_advance_method_line_ids.filtered(lambda x: x.code not in to_exclude)

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

    def _get_advance_method_codes_to_exclude(self):
        # can be overriden to exclude advance methods based on the advance characteristics
        self.ensure_one()
        return []

    @api.depends('journal_id')
    def _compute_currency_id(self):
        for pay in self:
            pay.currency_id = pay.journal_id.currency_id or pay.journal_id.company_id.currency_id

    @api.depends('journal_id')
    def _compute_partner_id(self):
        for pay in self:
            if pay.partner_id == pay.journal_id.company_id.partner_id:
                pay.partner_id = False
            else:
                pay.partner_id = pay.partner_id

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
                    pay.destination_account_id = pay.company_id.l10n_ec_payment_advance_customer_id
                else:
                    pay.destination_account_id = self.env['account.account'].with_company(pay.company_id).search([
                        *self.env['account.account']._check_company_domain(pay.company_id),
                        ('account_type', 'in', ['liability_current','liability_payable']),
                        ('deprecated', '=', False),
                    ], limit=1)
            elif pay.partner_type == 'supplier':
                # Send money to pay a bill or receive money to refund it.
                if pay.partner_id:
                    pay.destination_account_id = pay.company_id.l10n_ec_payment_advance_vendor_id
                else:
                    pay.destination_account_id = self.env['account.account'].with_company(pay.company_id).search([
                        *self.env['account.account']._check_company_domain(pay.company_id),
                        ('account_type', '=', 'asset_prepayments'),
                        ('deprecated', '=', False),
                    ], limit=1)

    @api.depends('partner_bank_id', 'amount', 'nro_document', 'currency_id', 'journal_id', 'move_id.state',
                 'advance_method_line_id', 'advance_type')

    def _compute_advance_receipt_title(self):
        """ To override in order to change the title displayed on the advance receipt report """
        self.advance_receipt_title = _('Anticipo')

\
    # -------------------------------------------------------------------------
    # ONCHANGE METHODS
    # -------------------------------------------------------------------------

    @api.onchange('partner_id')
    def _inverse_partner_id(self):
        """
            The goal of this inverse is that when changing the partner, the advance method line is recomputed, and it can
            happen that the journal that was set doesn't have that particular advance method line, so we have to change
            the journal otherwise the user will have an UserError.
        """
        for advance in self:
            partner = advance.partner_id
            advance_type = advance.advance_type if advance.advance_type in ('inbound', 'outbound') else None
            if not partner or not advance_type:
                continue

            field_name = f'property_{advance_type}_payment_method_line_id'
            default_advance_method_line = advance.partner_id.with_company(advance.company_id)[field_name]
            journal = default_advance_method_line.journal_id
            if journal:
                advance.journal_id = journal

    # -------------------------------------------------------------------------
    # CONSTRAINT METHODS
    # -------------------------------------------------------------------------

    @api.constrains('advance_method_line_id')
    def _check_advance_method_line_id(self):
        ''' Ensure the 'advance_method_line_id' field is not null.
        Can't be done using the regular 'required=True' because the field is a computed editable stored one.
        '''
        for pay in self:
            if not pay.advance_method_line_id:
                raise ValidationError(_("Please define a advance method line on your advance."))
            elif pay.advance_method_line_id.journal_id and pay.advance_method_line_id.journal_id != pay.journal_id:
                raise ValidationError(_("The selected advance method is not available for this advance, please select the advance method again."))

    @api.constrains('state', 'move_id')
    def _check_move_id(self):
        for advance in self:
            if (
                advance.state not in ('draft', 'canceled')
                and not advance.move_id
                and advance.origin_account_id
            ):
                raise ValidationError(_("A advance with an outstanding account cannot be confirmed without having a journal entry."))

    # -------------------------------------------------------------------------
    # LOW-LEVEL METHODS
    # -------------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        # OVERRIDE
        write_off_line_vals_list = []
        force_balance_vals_list = []
        linecomplete_line_vals_list = []

        for vals in vals_list:

            # Hack to add a custom write-off line.
            write_off_line_vals_list.append(vals.pop('write_off_line_vals', None))

            # Hack to force a custom balance.
            force_balance_vals_list.append(vals.pop('force_balance', None))

            # Hack to add a custom line.
            linecomplete_line_vals_list.append(vals.pop('line_ids', None))

        advances = super().create(vals_list)

        # Outstanding account should be set on the advance in community edition to force the generation of journal entries on the advance
        # This is required because no reconciliation is possible in community, which would prevent the user to reconcile the bank statement with the invoice
        accounting_installed = self.env['account.move']._get_invoice_in_payment_state() == 'in_advance'

        for i, (pay, vals) in enumerate(zip(advances, vals_list)):
            if not accounting_installed and not pay.origin_account_id:
                outstanding_account = pay._get_outstanding_account(pay.advance_type)
                pay.origin_account_id = outstanding_account.id

            if (
                write_off_line_vals_list[i] is not None
                or force_balance_vals_list[i] is not None
                or linecomplete_line_vals_list[i] is not None
            ):
                pay._generate_journal_entry(
                    write_off_line_vals=write_off_line_vals_list[i],
                    force_balance=force_balance_vals_list[i],
                    line_ids=linecomplete_line_vals_list[i],
                )
                # propagate the related fields to the move as it is being created after the advance
                if move_vals := {
                    fname: value
                    for fname, value in vals.items()
                    if self._fields[fname].related and (self._fields[fname].related or '').split('.')[0] == 'move_id'
                }:
                    pay.move_id.write(move_vals)
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
        if vals.get('state') == 'in_process' and not vals.get('move_id'):
            self.filtered(lambda p: not p.move_id)._generate_journal_entry()
            self.move_id.action_post()

        res = super().write(vals)
        if self.move_id:
            self._synchronize_to_moves(set(vals.keys()))
        return res

    def unlink(self):
        self.move_id.filtered(lambda m: m.state != 'draft').button_draft()
        self.move_id.unlink()

        linked_invoices = self.payment_ids
        res = super().unlink()
        self.env.add_to_compute(linked_invoices._fields['state'], linked_invoices)
        return res

    @api.depends('move_id.name')
    def _compute_display_name(self):
        for advance in self:
            advance.display_name = advance.name or _('Draft Advance')

    def copy_data(self, default=None):
        default = dict(default or {})
        vals_list = super().copy_data(default)
        for advance, vals in zip(self, vals_list):
            vals.update({
                'journal_id': advance.journal_id.id,
                'advance_method_line_id': advance.advance_method_line_id.id,
                **(vals or {}),
            })
        return vals_list

    # -------------------------------------------------------------------------
    # SYNCHRONIZATION account.advance -> account.move
    # -------------------------------------------------------------------------

    def _synchronize_to_moves(self, changed_fields):
        '''
            Update the account.move regarding the modified account.advance.
            :param changed_fields: A list containing all modified fields on account.advance.
        '''
        if not any(field_name in changed_fields for field_name in self._get_trigger_fields_to_synchronize()):
            return

        for pay in self:
            liquidity_lines, counterpart_lines, writeoff_lines = pay._seek_for_lines()
            # Make sure to preserve the write-off amount.
            # This allows to create a new advance with custom 'line_ids'.
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
            # Update the existing journal items.
            # If dealing with multiple write-off lines, they are dropped and a new one is generated.
            pay.move_id \
                .with_context(skip_invoice_sync=True) \
                .write({
                'partner_id': pay.partner_id.id,
                'currency_id': pay.currency_id.id,
                'partner_bank_id': pay.partner_bank_id.id,
                'line_ids': line_ids_commands,
            })

    @api.model
    def _get_trigger_fields_to_synchronize(self):
        return (
            'date', 'amount', 'advance_type', 'partner_type', 'reference',
            'currency_id', 'partner_id', 'destination_account_id', 'partner_bank_id', 'journal_id'
        )

    def _generate_journal_entry(self, write_off_line_vals=None, force_balance=None, line_ids=None):
        need_move = self.filtered(lambda p: not p.move_id and p.origin_account_id)
        assert len(self) == 1 or (not write_off_line_vals and not force_balance and not line_ids)

        move_vals = []
        for pay in need_move:
            move_vals.append({
                'move_type': 'entry',
                'ref': pay.nro_document,
                'date': pay.date,
                'journal_id': pay.journal_id.id,
                'company_id': pay.company_id.id,
                'partner_id': pay.partner_id.id,
                'currency_id': pay.currency_id.id,
                'partner_bank_id': pay.partner_bank_id.id,
                'line_ids': line_ids or [
                    Command.create(line_vals)
                    for line_vals in pay._prepare_move_line_default_vals(
                        write_off_line_vals=write_off_line_vals,
                        force_balance=force_balance,
                    )
                ],
                'origin_advance_id': pay.id,
            })
        moves = self.env['account.move'].create(move_vals)
        for pay, move in zip(need_move, moves):
            pay.write({'move_id': move.id, 'state': 'in_process'})

    def _get_advance_receipt_report_values(self):
        """ Get the extra values when rendering the Advance Receipt PDF report.

        :return: A dictionary:
            * display_invoices: Display the invoices table.
            * display_advance_method: Display the advance method value.
        """
        self.ensure_one()
        return {
            'display_invoices': True,
            'display_advance_method': True,
        }

    # -------------------------------------------------------------------------
    # BUSINESS METHODS
    # -------------------------------------------------------------------------

    def mark_as_sent(self):
        self.write({'is_sent': True})

    def unmark_as_sent(self):
        self.write({'is_sent': False})

    def action_post(self):
        ''' draft -> posted '''
        # Do not allow posting if the account is required but not trusted
        for advance in self:
            if advance.require_partner_bank_account and not advance.partner_bank_id.allow_out_advance:
                raise UserError(_(
                    "To record advances with %(method_name)s, the recipient bank account must be manually validated. "
                    "You should go on the partner bank account of %(partner)s in order to validate it.",
                    method_name=self.advance_method_line_id.name,
                    partner=advance.partner_id.display_name,
                ))
        # Avoid going back one state when clicking on the confirm action in the advance list view and having paid expenses selected
        # We need to set values to each advance to avoid recomputation later
        self.filtered(lambda pay: pay.state in {False, 'draft', 'in_process'}).state = 'in_process'

    def action_validate(self):
        self.state = 'paid'

    def action_reject(self):
        self.state = 'rejected'

    def action_cancel(self):
        self.state = 'canceled'
        draft_moves = self.move_id.filtered(lambda m: m.state == 'draft')
        draft_moves.unlink()
        (self.move_id - draft_moves).button_cancel()

    def button_request_cancel(self):
        return self.move_id.button_request_cancel()

    def action_draft(self):
        self.state = 'draft'
        self.move_id.button_draft()

    def button_open_invoices(self):
        ''' Redirect the user to the invoice(s) paid by this advance.
        :return:    An action on account.move.
        '''
        self.ensure_one()
        return (self.advance_ids).with_context(
            create=False
        )._get_records_action(
            name=_("Paid Invoices"),
        )

    def button_open_bills(self):
        ''' Redirect the user to the bill(s) paid by this advance.
        :return:    An action on account.move.
        '''
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

    def button_open_journal_entry(self):
        ''' Redirect the user to this advance journal.
        :return:    An action on account.move.
        '''
        self.ensure_one()
        return {
            'name': _("Diario contable"),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'context': {'create': False},
            'view_mode': 'form',
            'res_id': self.move_id.id,
        }
