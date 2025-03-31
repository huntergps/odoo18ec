from odoo import fields, models, api, Command, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.misc import format_date


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    advance_id = fields.Many2one('account.advance', string='Anticipo')

    type_mov = fields.Selection(selection_add=[
        ('cross', 'Cruce de Cartera'),
        ('other', 'Otros Pagos'),
    ], ondelete={'cross': 'set default','other': 'set default'})
    
    # Campo para mostrar los anticipos disponibles para el partner seleccionado
    available_advance_ids = fields.Many2many(
        'account.advance', 
        compute='_compute_available_advances',
        string='Anticipos Disponibles'
    )
    
    # Monto disponible del anticipo seleccionado
    advance_available_amount = fields.Monetary(
        string='Monto Disponible en Anticipo',
        currency_field='currency_id',
        compute='_compute_advance_available_amount'
    )

    cheque_emitido_id = fields.Many2one('cheque.emitido', string='Cheque Emitido')
    cheque_recibido_id = fields.Many2one('cheque.recibido', string='Cheque Recibido')
    
    # Campos relacionados para mostrar información del cheque en la vista
    cheque_no = fields.Char(related='cheque_emitido_id.cheque_no', string='Número de Cheque', readonly=True)
    name_in_cheque = fields.Char(string='Nombre en el Cheque', tracking=True)
    cheque_state = fields.Selection(related='cheque_emitido_id.state', string='Estado del Cheque', readonly=True)
    cheque_date = fields.Date(string='Fecha del Cheque', default=fields.Date.context_today, required=True, tracking=True)
    cheque_date_efective = fields.Date(string='Fecha Efectiva de Cobro', default=fields.Date.context_today, required=True, tracking=True)

    # === Transferencias ===
    transfer_number = fields.Char(string="Número de Transferencia", tracking=True)
    transfer_date = fields.Date(string="Fecha de Transferencia", default=fields.Date.context_today)

    # === Tarjetas ===
    card_brand_id = fields.Many2one('account.credit.card.brand', string='Marca de Tarjeta')
    card_deadline_id = fields.Many2one('account.credit.card.deadline', string='Plazo de Tarjeta')
    card_type = fields.Selection([
        ('credit', 'Tarjeta de Crédito'),
        ('debit', 'Tarjeta de Débito')
    ], string='Tipo de Tarjeta')


    reposicion_caja_chica_id = fields.Many2one('caja.chica.reposicion',tracking=True, string="Reposicion de Caja Chica")

    lote_id = fields.Many2one('account.card.lote', string='Lote',tracking=True)

    @api.onchange('payment_method_line_id')
    def _onchange_payment_method_line_id_extra_fields(self):
        if self.payment_method_line_id.code == 'bank_transfer':
            self.transfer_date = fields.Date.context_today(self)
            self.card_type = False
        elif self.payment_method_line_id.code == 'card_credit':
            self.card_type = 'credit'
        elif self.payment_method_line_id.code == 'card_debit':
            self.card_type = 'debit'
        else:
            self.card_type = False  # Limpia si cambia a otro método

    @api.depends('company_id', 'payment_type', 'type_mov')
    def _compute_available_journal_ids(self):
        """
        Get all journals having at least one payment method for inbound/outbound depending on the payment_type.
        """
        journal_types = ['bank', 'cash', 'credit','advance']
        if self.type_mov == 'other':
            journal_types = ['general']
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
            if any(journal_type in ['bank', 'cash', 'credit','advance'] for journal_type in journal_types):
                # Filtrar según el tipo de pago (inbound/outbound)
                if pay.payment_type == 'inbound':
                    pay.available_journal_ids = journals.filtered('inbound_payment_method_line_ids')
                else:
                    pay.available_journal_ids = journals.filtered('outbound_payment_method_line_ids')
            else:
                pay.available_journal_ids = journals

    @api.depends('partner_id', 'type_mov', 'payment_type')
    def _compute_available_advances(self):
        """Calcular los anticipos disponibles para el partner seleccionado"""
        for payment in self:
            if payment.type_mov == 'current' and payment.partner_id:
                # Si es entrada de dinero (pago recibido), buscar anticipos enviados
                advance_type = 'inbound' if payment.payment_type == 'inbound' else 'outbound'
                # advance_type = 'outbound' if payment.payment_type == 'inbound' else 'inbound'
                partner_type = 'customer' if payment.partner_type == 'customer' else 'supplier'
                
                advances = self.env['account.advance'].search([
                    ('partner_id', '=', payment.partner_id.id),
                    ('partner_type', '=', partner_type),
                    ('advance_type', '=', advance_type),
                    ('state', '=', 'posted'),
                    ('amount_available', '>', 0)
                ])
                payment.available_advance_ids = advances
            else:
                payment.available_advance_ids = False

    @api.depends('advance_id')
    def _compute_advance_available_amount(self):
        """Mostrar el monto disponible del anticipo seleccionado"""
        for payment in self:
            if payment.advance_id:
                payment.advance_available_amount = payment.advance_id.amount_available
            else:
                payment.advance_available_amount = 0

    @api.onchange('type_mov')
    def _onchange_type_mov(self):
        """Limpiar el anticipo seleccionado cuando cambia el tipo de movimiento"""
        if self.type_mov != 'current':
            self.advance_id = False
        elif self.type_mov == 'current' and self.partner_id:
            # Autoseleccionar el primer anticipo disponible
            if self.available_advance_ids:
                self.advance_id = self.available_advance_ids[0]

    @api.onchange('advance_id', 'amount')
    def _onchange_advance_id(self):
        """Ajustar el monto del pago al seleccionar un anticipo"""
        if self.type_mov == 'current' and self.advance_id:
            # Verificar que el monto no supere el disponible
            if self.amount > self.advance_id.amount_available:
                self.amount = self.advance_id.amount_available
            
    @api.constrains('type_mov', 'advance_id', 'amount')
    def _check_advance_amount(self):
        """Validar que el monto no exceda el disponible en el anticipo"""
        for payment in self:
            if payment.type_mov == 'current' and payment.advance_id:
                if payment.amount > payment.advance_id.amount_available:
                    raise ValidationError(_(
                        "El monto del pago (%s) excede el monto disponible en el anticipo (%s).",
                        payment.amount, payment.advance_id.amount_available
                    ))
    
    @api.onchange('amount')
    def _onchange_amount(self):
        """Actualizar el monto en el cheque si hay uno seleccionado"""
        if self.cheque_emitido_id and self.state == 'draft' and self.amount > 0:
            self.cheque_emitido_id.amount = self.amount

    @api.onchange('partner_id')
    def _onchange_partner_id_update_cheque(self):
        """Actualizar nombre en cheque al cambiar el partner"""
        if self.partner_id:
            self.name_in_cheque = self.partner_id.name

    @api.constrains('journal_id', 'type_mov')
    def _check_journal_type(self):
        for payment in self:
            if payment.type_mov == 'cross' and payment.journal_id.type != 'cross':
                raise ValidationError("Para transacciones de tipo 'Cruce de Cartera', seleccione un diario de tipo 'Cruce de Cartera'.")


    @api.onchange('payment_method_line_id', 'partner_id')
    def _onchange_payment_method_line_id(self):
        """Al cambiar el método de pago a cheque, mostrar los cheques disponibles"""
        
        if self.payment_method_line_id.code == 'check_printing' and self.payment_type == 'outbound':
            # Cargar cheques disponibles si el método es cheque
            available_cheques = self.env['cheque.emitido'].search([
                ('state', '=', 'new'),
                ('bank_account_id', '=', self.journal_id.id)
            ], order='cheque_no')

            if not available_cheques:
                return {
                    'warning': {
                        'title': _('Sin cheques disponibles'),
                        'message': _('No hay cheques disponibles en la chequera. Por favor genere una nueva chequera.')
                    }
                }
            else:
                # Seleccionar automáticamente el primer cheque disponible
                self.cheque_emitido_id = available_cheques[0]
        else:
            # Limpiar el cheque seleccionado si cambia el método de pago
            self.cheque_emitido_id = False

    @api.onchange('name_in_cheque')
    def _onchange_name_in_cheque(self):
        """Sincronizar el cambio del nombre en el cheque con el registro del cheque"""
        if self.cheque_emitido_id and self.name_in_cheque:
            self.cheque_emitido_id.name_in_cheque = self.name_in_cheque

    @api.onchange('cheque_emitido_id')
    def _onchange_cheque_emitido(self):
        """Al seleccionar un cheque, actualizar los campos relacionados"""
        if self.cheque_emitido_id:
            self.cheque_emitido_id.partner_id = self.partner_id
            self.cheque_emitido_id.amount = self.amount
            # Actualizar información del cheque con fecha actual
            self.cheque_emitido_id.cheque_date = fields.Date.context_today(self)
            self.cheque_emitido_id.cheque_date_efective = fields.Date.context_today(self)
            # Sincronizar el nombre en el cheque
            if self.name_in_cheque:
                self.cheque_emitido_id.name_in_cheque = self.name_in_cheque
            else:
                self.name_in_cheque = self.cheque_emitido_id.name_in_cheque or self.partner_id.name

    def action_post(self):
        """Sobrescribir para validar y actualizar los cheques al publicar el pago"""
        # Verificar si es un pago con cheque
        for payment in self:
            if payment.payment_method_line_id.code == 'check_printing' and payment.payment_type == 'outbound':
                if not payment.name_in_cheque:
                    raise UserError(_("Debe ingresar el nombre en el cheque."))
                if not payment.cheque_date or not payment.cheque_date_efective:
                    raise UserError(_("Debe ingresar la fecha del cheque y la fecha efectiva."))
                
                if not payment.cheque_emitido_id:
                    # Buscar un cheque disponible
                    available_cheque = self.env['cheque.emitido'].search([
                        ('state', '=', 'new'),
                        ('bank_account_id', '=', payment.journal_id.id)
                    ], order='cheque_no', limit=1)
                    
                    if not available_cheque:
                        raise UserError(_("No hay cheques disponibles en la chequera. Por favor genere una nueva chequera."))
                    
                    # Asignar el cheque al pago
                    payment.cheque_emitido_id = available_cheque.id
                
                # Actualizar datos del cheque
                payment.cheque_emitido_id.write({
                    'partner_id': payment.partner_id.id,
                    'name_in_cheque': payment.name_in_cheque or payment.partner_id.name,
                    'amount': payment.amount,
                    'cheque_date': fields.Date.context_today(payment),
                    'cheque_date_efective': fields.Date.context_today(payment),
                    'state': 'used',
                    'type_mov': payment.type_mov or 'current',
                })        
        """Actualizar la relación entre factura y anticipo al confirmar el pago"""
        result = super(AccountPayment, self).action_post()
        return result
        

    def action_draft(self):
        """Al volver a borrador, también actualizar el estado del cheque"""
        res = super(AccountPayment, self).action_draft()
        for payment in self:
            if payment.cheque_emitido_id and payment.cheque_emitido_id.state == 'used':
                payment.cheque_emitido_id.write({
                    'state': 'new',
                    'partner_id': False,
                    'amount': 0.0,
                })
        return res

    def action_cancel(self):
        """Al cancelar, liberar el cheque asignado"""
        for payment in self:
            if payment.cheque_emitido_id and payment.cheque_emitido_id.state == 'used':
                # Si el cheque está impreso pero no cobrado, marcarlo como cancelado
                if payment.cheque_emitido_id.state in ['used', 'printed', 'issued']:
                    payment.cheque_emitido_id.write({
                        'state': 'cancelled',
                        'cancel_date': fields.Date.context_today(payment),
                    })
        
        return super(AccountPayment, self).action_cancel()

    def action_generate_checkbook(self):
        """Método para abrir el wizard de generación de chequera desde el pago"""
        if not self.journal_id:
            raise UserError(_("Debe seleccionar un diario bancario antes de generar una chequera."))
            
        return {
            'type': 'ir.actions.act_window',
            'name': _('Recepción de Chequera'),
            'res_model': 'recibir.chequera',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_bank_account_id': self.journal_id.id,
            }
        }

