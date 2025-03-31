from odoo import models, api, Command, fields, _


class AccountJournal(models.Model):
    _inherit = ["account.journal"]

    payment_type = fields.Selection([
        ('', 'No aplica'),
        ('outbound', 'Enviar'),
        ('inbound', 'Recibir'),
    ], string='Tipo de pago', default='',  tracking=True)

    type = fields.Selection(selection_add=[
        ('advance', 'Anticipo'),
        ('cross', 'Cruce de Cartera'),
    ], ondelete={'advance': 'set general', 'cross': 'set general'})

    tiene_chequera = fields.Boolean(string='Tiene Chequera', default=False,
                                   help="Marque esta opción si este diario bancario tiene chequera")

    caja_chica = fields.Boolean('Es Caja Chica', default=False)
    fondo_rendir = fields.Boolean('Es para Fondo a Rendir', default=False)

    @api.onchange('caja_chica')
    def onchange_caja_chica(self):
        for rec in self:
            rec.fondo_rendir=not(rec.caja_chica)

    @api.onchange('fondo_rendir')
    def onchange_fondo_rendir(self):
        for rec in self:
            rec.caja_chica=not(rec.fondo_rendir)



    def _get_default_account_domain(self):
        domain = super(AccountJournal, self)._get_default_account_domain()

        # Extender la lógica para permitir la selección de cuentas de anticipo
        if self.type == 'advance':
            domain = """[
                ('deprecated', '=', False),
                ('account_type', '=', 'asset_prepayments')
            ]"""
        elif self.type == 'cross':
            domain = """[
                ('deprecated', '=', False),
                ('account_type', '=', 'liability_payable')
            ]"""
        else:
            domain = super(AccountJournal, self)._get_default_account_domain()

        return domain

    @api.depends('type', 'currency_id')
    def _compute_inbound_payment_method_line_ids(self):
        for journal in self:
            pay_method_line_ids_commands = [Command.clear()]
            if journal.type in ('bank', 'cash', 'credit','advance','cross'):
                default_methods = journal._default_inbound_payment_methods()
                pay_method_line_ids_commands += [Command.create({
                    'name': pay_method.name,
                    'payment_method_id': pay_method.id,
                }) for pay_method in default_methods]
            journal.inbound_payment_method_line_ids = pay_method_line_ids_commands

    @api.depends('type', 'currency_id')
    def _compute_outbound_payment_method_line_ids(self):
        print("**** _compute_outbound_payment_method_line_ids ***")
        for journal in self:
            pay_method_line_ids_commands = [Command.clear()]
            if journal.type in ('bank', 'cash', 'credit','advance','cross'):
                default_methods = journal._default_outbound_payment_methods()
                pay_method_line_ids_commands += [Command.create({
                    'name': pay_method.name,
                    'payment_method_id': pay_method.id,
                }) for pay_method in default_methods]
            journal.outbound_payment_method_line_ids = pay_method_line_ids_commands



    def _default_inbound_payment_methods(self):
        res = super()._default_inbound_payment_methods()
        if self.company_id.country_id.code != "EC":
            return res
        if self._is_payment_method_available('deposit_cheque'):
            res |= self.env.ref('l10n_ec_payment.account_payment_method_deposit_cheque_in')
        if self._is_payment_method_available('card_credit'):
            res |= self.env.ref('l10n_ec_payment.account_payment_method_credit_card_in')
        if self._is_payment_method_available('transf'):
            res |= self.env.ref('l10n_ec_payment.account_payment_method_transf_in')
        if self._is_payment_method_available('card_debit'):
            res |= self.env.ref('l10n_ec_payment.account_payment_method_debit_card_in')
        print('_default_inbound_payment_methods:',res)
        return res


    def _default_outbound_payment_methods(self):
        res = super()._default_outbound_payment_methods()
        if self.company_id.country_id.code != "EC":
            return res
        if self._is_payment_method_available('card_debit'):
            res |= self.env.ref('l10n_ec_payment.account_payment_method_debit_card_out')
        if self._is_payment_method_available('card_credit'):
            res |= self.env.ref('l10n_ec_payment.account_payment_method_credit_card_out')
        if self._is_payment_method_available('transf'):
            res |= self.env.ref('l10n_ec_payment.account_payment_method_transf_out')
        if self._is_payment_method_available('bank_debit'):
            res |= self.env.ref('l10n_ec_payment.account_payment_method_bank_debit_out')
        print('_default_outbound_payment_methods:',res)
        return res

    @api.model
    def _get_reusable_payment_methods(self):
        """ We are able to have multiple times Checks payment method in a journal """
        res = super()._get_reusable_payment_methods()
        res.add("card_credit")
        return res
