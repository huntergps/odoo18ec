# -*- coding: utf-8 -*-

from odoo.exceptions import UserError, ValidationError
from odoo import api, fields, models, _
from datetime import datetime, timedelta

class ChequeEmitido(models.Model):
    _name = "cheque.emitido"
    _description = "Cheque Emitido"
    _inherit = ['mail.thread', 'mail.activity.mixin']

    # -------------------------------------------------------------------------
    # CAMPOS DE NEGOCIO
    # -------------------------------------------------------------------------
    comprobante_pago_ids = fields.One2many('account.payment', 'cheque_emitido_id')
    name = fields.Char(string='Comprobante Ref', readonly=True)
    cheque_no = fields.Char(string='Cheque Nro.', readonly=True, tracking=True)
    bank_account_id = fields.Many2one('account.journal', string="Diario de Cuenta Bancaria", readonly=True, tracking=True)
    partner_bank_account_id = fields.Many2one('res.partner.bank', string="Cuenta Bancaria", readonly=True, domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]")
    cheque_date = fields.Date(string='Fecha del Cheque', readonly=True, tracking=True)
    cheque_date_print = fields.Date(string='Impreso el', tracking=True, readonly=True)
    cheque_date_efective = fields.Date(string='Fecha Efectiva de Cobro', tracking=True)
    hold_date = fields.Date(string='Fecha de Retención', readonly=True)
    return_date = fields.Date(string='Fecha de Devolución', tracking=True, readonly=True)
    cancel_date = fields.Date(string='Fecha de Cancelación', tracking=True, readonly=True)
    lost_date = fields.Date(string='Fecha de Pérdida', tracking=True, readonly=True)
    partner_id = fields.Many2one('res.partner', string="Emitido a", tracking=True, readonly=True)
    name_in_cheque = fields.Char(string="Nombre en el Cheque")
    partner_account_id = fields.Many2one('account.account', string="Cuenta contable", readonly=True)
    receiver_name = fields.Char(string='Nombre del Receptor')
    designation = fields.Char(string='Cargo del Receptor')
    phone = fields.Char(string='Teléfono del Receptor')
    cheque_date_issue = fields.Date(string='Fecha de Emisión', tracking=True)
    account_move_ids = fields.Many2many('account.move','cheque_emitido_move_rel', 'cheque_id', 'move_id', 'Asientos relacionados', readonly=True)
    state = fields.Selection([
        ('new', 'Nuevo'),
        ('used', 'Usado'),
        ('printed', 'Impreso'),
        ('issued', 'Entregado'),
        ('pending', 'Pendiente'),
        ('cleared', 'Cobrado'),
        ('returned', 'Devuelto'),
        ('cancelled', 'Cancelado'),
        ('lost', 'Perdido'),
    ], string='Estado', tracking=True, readonly=True)
    comment = fields.Text(string="Comentarios")
    amount = fields.Float('Monto', readonly=True)
    type_mov = fields.Selection([
        ('current', 'Pago Ordinario'),
        ('advance', 'Anticipo de Pago'),
        ('other', 'Otro Pago'),
    ], string='Tipo de Transacción', default = 'current', readonly=True)
    currency_id = fields.Many2one('res.currency', string='Moneda', required=True,
        readonly=True, default=lambda self: self.env.company.currency_id)
    check_amount_in_words = fields.Char(string="Monto en Palabras")

    # -------------------------------------------------------------------------
    # MÉTODOS DE AYUDA
    # -------------------------------------------------------------------------
    @api.onchange('amount', 'currency_id')
    def _onchange_amount(self):
        res = super(ChequeEmitido, self)._onchange_amount()
        self.check_amount_in_words = self.currency_id.amount_to_text(self.amount).replace("Dollars","Dólares") if self.currency_id else ''
        return res

    def set_check_amount_in_words(self):
        for payment in self:
            payment.check_amount_in_words = payment.currency_id.amount_to_text(payment.amount).replace("Dollars","Dólares") if payment.currency_id else ''

    @api.onchange('partner_id')
    def onchange_type_mov(self):
        for rec in self:
            if not rec.name_in_cheque:
                if rec.partner_id:
                    rec.name_in_cheque = rec.partner_id.name

    # -------------------------------------------------------------------------
    # MÉTODOS DE VALIDACIÓN
    # -------------------------------------------------------------------------
    @api.constrains('amount')
    def _check_amount_positive(self):
        """Valida que el monto del cheque sea positivo"""
        for cheque in self:
            if cheque.amount <= 0 and cheque.state not in ('new', 'cancelled', 'lost'):
                raise ValidationError(_("El monto del cheque debe ser mayor a 0."))

    @api.constrains('cheque_date', 'cheque_date_efective')
    def _check_dates_consistency(self):
        """Valida la consistencia entre las fechas del cheque"""
        for cheque in self:
            if cheque.cheque_date and cheque.cheque_date_efective and cheque.cheque_date > cheque.cheque_date_efective:
                raise ValidationError(_("La fecha efectiva de cobro no puede ser anterior a la fecha del cheque."))

    @api.constrains('state', 'cheque_no')
    def _check_cheque_number_format(self):
        """Valida el formato del número de cheque"""
        for cheque in self:
            if cheque.state not in ('new', 'cancelled') and not cheque.cheque_no:
                raise ValidationError(_("El número de cheque es obligatorio."))

    # -------------------------------------------------------------------------
    # MÉTODOS DE NEGOCIO
    # -------------------------------------------------------------------------
    def write(self, values):
        if 'cheque_date' in values and 'cheque_date_efective' not in values:
            values['cheque_date_efective'] = values['cheque_date']
        result = super(ChequeEmitido, self).write(values)
        return result

    def lost_cheque(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Cheque Perdido',
            'view_mode': 'form',
            'res_model': 'lost.cheque',
            'target': 'new',
            'context': 'None'
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
        config_obj = self.env['cheque.config.settings'].search([], order='id desc', limit=1)
        alert_days = config_obj.alert_outbound
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
            conf = self.env['cheque.config.settings'].search([], order='id desc', limit=1)
            vals = {'state': 'outgoing',
                    'subject': 'Lista de Cheques Emitidos Pendientes',
                    'body_html': """<div>
                                        <p>Hola,</p>
                                        <p>Este es un recordatorio generado por el sistema. Los siguientes cheques emitidos están pendientes.</p>
                                    </div>
                                    <blockquote>%s</blockquote>
                                    <div>Gracias</div>""" % (cheques),
                    'email_to': conf.email,
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
            # Crear una actividad programada para el responsable de tesorería
            self._create_pending_cheque_activity()
        elif self.state == 'hold' and self.hold_date < today:
            self.write({'state': 'pending'})
            self._create_pending_cheque_activity()

    def _create_pending_cheque_activity(self):
        """Crea una actividad para notificar sobre cheques pendientes"""
        activity_type_id = self.env.ref('mail.mail_activity_data_todo').id
        treasury_user = self.env['res.users'].search([('groups_id', 'in', self.env.ref('account.group_account_manager').id)], limit=1)
        
        if treasury_user:
            self.env['mail.activity'].create({
                'activity_type_id': activity_type_id,
                'note': _('El cheque %s por %s %s ha pasado a estado pendiente. Requiere verificación.') % 
                        (self.cheque_no, self.currency_id.symbol, self.amount),
                'user_id': treasury_user.id,
                'res_id': self.id,
                'res_model_id': self.env['ir.model']._get('cheque.emitido').id,
                'summary': _('Cheque pendiente de cobro'),
                'date_deadline': fields.Date.today(),
            })

    def print_cheque(self):
        # Validar monto y fecha antes de imprimir
        if not self.amount or self.amount <= 0:
            raise UserError(_("No se puede imprimir un cheque con monto cero o negativo."))
        
        if not self.partner_id:
            raise UserError(_("Debe especificar el beneficiario del cheque antes de imprimirlo."))
        
        self.state = 'printed'
        self.cheque_date_print = datetime.now()
        self.set_check_amount_in_words()
        return self.env.ref('mass_payment.action_report_chequeemitido').report_action(self)

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

    def borrador_cheque(self):
        if self.state in ('used','cancelled'):
            if len(self.comprobante_pago_ids)>0:
                for pago in self.comprobante_pago_ids:
                    if pago.payment_method_code=='cheque':
                        raise UserError("Está tratando de poner en Borrador un cheque usado")
            self.write({'state':'new','comprobante_pago_ids':False})
            self.flush()

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

    def action_generar_chequera(self):
        """
        Método que abre el wizard para generar chequera
        """
        return {
            'type': 'ir.actions.act_window',
            'name': 'Recepción de Chequera',
            'res_model': 'recibir.chequera',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_bank_account_id': self.bank_account_id.id if self.bank_account_id else False,
            }
        }
