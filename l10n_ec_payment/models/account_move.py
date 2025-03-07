# Part of Odoo. See LICENSE file for full copyright and licensing details.
from odoo import models, fields, api, _, Command

# a lot of SQL queries
class AccountMove(models.Model):
    _inherit = ['account.move']

    advance_ids = fields.One2many('account.advance', 'move_id', string='Anticipos')

    # === Advance fields === #
    origin_advance_id = fields.Many2one(  # the advance this is the journal entry of
        comodel_name='account.advance',
        string="Anticipo",
        index='btree_not_null',
        copy=False,
        check_company=True,
    )


    def action_open_business_doc(self):
        if self.origin_advance_id:
            name = _("Anticipo")
            res_model = 'account.advance'
            res_id = self.origin_advance_id.id
            return {
                'name': name,
                'type': 'ir.actions.act_window',
                'view_mode': 'form',
                'views': [(False, 'form')],
                'res_model': res_model,
                'res_id': res_id,
                'target': 'current',
            }
        else:
            return super().action_open_business_doc()
