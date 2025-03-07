# my_module/models/res_partner.py
from odoo import models, api, fields, _
from odoo.exceptions import ValidationError

class ResPartner(models.Model):
    _inherit = 'res.partner'

    external_id = fields.Char('Id DB Externa', index=True)
    acepta_cheques = fields.Boolean('Aceptar Cheques', tracking=True,
    help="Se acepta cheques de este contacto como  Cliente")

    last_day_to_invoice = fields.Integer(
        string="Acepta Facturas hasta",
        default=0,
        help="Indicar el ultimo día del mes que se puede facturar, si el "
             "Cliente compra facturas pasada esta fecha, se dejara en espera "
             "hasta el primer dia del Siguiente mes"
    )

    no_invoice = fields.Boolean(
        string="No emitir facturas",
        default=False,
        tracking=True,
        help="No se podrá emitir facturas si esta opción esta marcada "
    )

    terminos_pagos_ids = fields.Many2many(
        'account.payment.term',
        'res_partner_payment_term_rel',
        'res_partner_id',
        'payment_term_id',
        string='Terminos de Pago autorizados en Ventas',
        tracking=True,
        help="Seleccione los terminos de pagos autorizados para este contacto en Ventas"
    )

    terminos_pagos_supplier_ids = fields.Many2many(
        'account.payment.term',
        'res_partner_payment_term_supplier_rel',
        'res_partner_id',
        'payment_term_id',
        string='Terminos de Pago autorizados en Compras',
        tracking=True,
        help="Seleccione los terminos de pagos autorizados para este contacto en Compras"
    )


    can_edit_credit_payment_terms = fields.Boolean(compute='_compute_can_edit_credit_payment_terms', string="Puede Editar Términos de Pago")

    @api.depends('user_id')
    def _compute_can_edit_credit_payment_terms(self):
        for partner in self:
            partner.can_edit_credit_payment_terms = self.env.user.has_group('l10n_ec_base.group_allow_change_credit_payment_terms')


    @api.model_create_multi
    def create(self, vals):
        if 'vat' in vals and vals['vat']:
            self._check_vat_uniqueness(vals['vat'])
        return super(ResPartner, self).create(vals)

    def write(self, vals):
        if 'vat' in vals and vals['vat']:
            self._check_vat_uniqueness(vals['vat'])
        return super(ResPartner, self).write(vals)

    def copy(self, default=None):
        self.ensure_one()  # Ensure that only one record is being copied
        if self.vat:
            self._check_vat_uniqueness(self.vat)
        return super(ResPartner, self).copy(default)

    def _check_vat_uniqueness(self, vat):
        if not self.env.user.has_group('l10n_ec_base.group_allow_duplicate_vat'):
            for rec in self:
                existing_partner = rec.search([('vat', '=', vat), ('id', '!=', rec.id)], limit=1)
                if existing_partner:
                    raise ValidationError(_('El número de Identificación Tributaria %s ya está registrado para otro contacto: %s.') % (vat, existing_partner.name))
