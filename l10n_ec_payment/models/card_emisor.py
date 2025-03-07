# -*- coding: utf-8 -*-

from odoo import api, fields, models



class CreditCardBrand(models.Model):
    _name = "account.credit.card.brand"
    _description ="Marcas de Tarjeta de Credito"

    code = fields.Char(string='Código de la Tarjeta')
    name = fields.Char(string='Nombre de la Tarjeta', required=True)
    credit = fields.Boolean(string="Tarjetas de Crédito")
    debit = fields.Boolean(string="Tarjetas de Débito")

    _sql_constraints = [('name_uniq', 'unique (name)', 'El nombre de la marca de la tarjeta debe ser único. !')]


class CreditCardDeadLine(models.Model):
    _name = "account.credit.card.deadline"
    _description ="Plazos de Tarjeta de Credito"

    name = fields.Char(string='Descripción', required=True)
    type = fields.Selection([
        ('current', 'Corriente'),
        ('deferred', 'Diferido')
    ], string='Tipo', default='current', required=True)
    meses = fields.Boolean(string="Plazos en meses")
    interes = fields.Boolean(string="Con interes")
    credit = fields.Boolean(string="Tarjetas de Crédito")
    debit = fields.Boolean(string="Tarjetas de Débito")

    _sql_constraints = [('name_uniq', 'unique (name)', 'El nombre de la marca de la tarjeta debe ser único. !')]



class ReturnReason(models.Model):
    _name = "return.reason"
    _description ="Motivo de Devolución de cheques"

    name = fields.Char(string='Reason', required=True)
    comment_required = fields.Boolean(string="Comentarios Required ?")
    _sql_constraints = [('name_uniq', 'unique (name)', 'The reason must be unique !')]
