from odoo import api, fields, models, Command, _

from odoo.exceptions import UserError, ValidationError


class AccountMove(models.Model):
    _inherit = 'account.move'

    edocument_id = fields.Many2one('edocument', string='Documento Electronico', copy=False)



class AccountMoveLine(models.Model):
    """ Override AccountInvoice_line to add the link to the purchase order line it is related to"""
    _inherit = ['account.move.line']

    edocument_line_id = fields.Many2one('edocument.line', 'Linea Documento Electronico', ondelete='set null', index='btree_not_null', copy=False)
    edocument_order_id = fields.Many2one('edocument', 'Documento Electronico', related='edocument_line_id.order_id', readonly=True)

    def _copy_data_extend_business_fields(self, values):
        # OVERRIDE to copy the 'purchase_line_id' field as well.
        super(AccountMoveLine, self)._copy_data_extend_business_fields(values)
        values['edocument_line_id'] = self.edocument_line_id.id
