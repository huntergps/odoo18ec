from odoo import models, api


class AccountPaymentMethod(models.Model):
    _inherit = ['account.payment.method']

    @api.model
    def _get_payment_method_information(self):
        res = super()._get_payment_method_information()
        res['deposit_cheque'] = {'mode': 'multi', 'type': ('bank',)}
        res['checks'] = {'mode': 'multi', 'type': ('bank','cash')}
        res['card_credit'] = {'mode': 'multi', 'type': ('bank','credit')}
        res['card_debit'] = {'mode': 'multi', 'type': ('bank',)}
        res['transf'] = {'mode': 'multi', 'type': ('bank',)}
        res['advance'] = {'mode': 'multi', 'type': ('bank',)}
        res['bank_debit'] = {'mode': 'multi', 'type': ('bank','credit')}
        return res
