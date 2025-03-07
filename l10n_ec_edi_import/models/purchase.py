# -*- encoding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from collections import defaultdict

from odoo import api, fields, models, _, Command
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT, get_lang



class PurchaseOrder(models.Model):
    _inherit = ['purchase.order']

    date_approve = fields.Datetime('Confirmation Date', readonly=False, index=True, copy=False)
    edocument_id = fields.Many2one('edocument', string='Documento Electronico', copy=False)

    def onchange_edocument_id(self):
        self._onchange_edocument_id()


    @api.onchange('edocument_id')
    def _onchange_edocument_id(self):
        if not self.edocument_id:
            return
        self = self.with_company(self.company_id)
        edocument = self.edocument_id
        if self.partner_id:
            partner_id = self.partner_id
        else:
            partner_id = edocument.partner_id
        payment_term = partner_id.property_supplier_payment_term_id
        FiscalPosition = self.env['account.fiscal.position']
        fpos = FiscalPosition.with_company(self.company_id)._get_fiscal_position(partner_id)
        self.partner_id = partner_id.id
        self.fiscal_position_id = fpos.id
        self.payment_term_id = payment_term.id
        self.company_id = edocument.company_id.id
        self.currency_id = edocument.currency_id.id
        self.partner_ref = edocument.partner_ref
        self.origin = edocument.name
        self.notes = edocument.notes
        # self.date_order = fields.Datetime.now()
        self.date_order: edocument.fecha_emision
        self.date_planned: edocument.fecha_emision
        # Procesar líneas del documento electrónico
        order_lines = []
        lines_to_process = edocument.order_line
        lines_to_unify = edocument.order_line.filtered(lambda line: line.unificar)
        # lines_to_distribute = edocument.order_line.filtered(lambda line: line.distribuir_code)
        lines_to_distribute = edocument.order_line.filtered(lambda line: line.distribuir_code and line.distribuir_code.strip())
        print("-"*50)
        print('lines_to_process : ',lines_to_process)
        print()
        print('lines_to_unify : ',lines_to_unify)
        print()

        print('lines_to_distribute : ',lines_to_distribute)
        print()

        for line in lines_to_process - lines_to_unify - lines_to_distribute:
            # Compute taxes
            taxes_ids = fpos.map_tax(line.product_id.supplier_taxes_id.filtered(lambda tax: tax.company_id == edocument.company_id)).ids
            # Compute quantity and price_unit
            if line.product_uom_id != line.product_id.uom_id:
                product_qty = line.product_uom_id._compute_quantity(line.product_qty, line.product_id.uom_id)
                price_unit = line.product_uom_id._compute_price(line.price_unit, line.product_id.uom_id)
            else:
                product_qty = line.product_qty
                price_unit = line.price_unit


            # # Create PO line
            order_line_values=line._prepare_purchase_order_line( line.product_id, product_qty, line.product_uom_id,line.discount, line.company_id, partner_id, self)
            order_lines.append((0, 0, order_line_values))

        # Unificar líneas usando método de edocument
        if len(lines_to_unify)>0:
            unified_lines = edocument._unify_lines(lines_to_unify, fpos, edocument.company_id, partner_id, self)
            for unified_line in unified_lines:
                order_lines.append((0, 0, unified_line))
            print("-"*50)
            print(unified_lines)
        # # Distribuir líneas usando método de edocument
        if len(lines_to_distribute)>0:
            distributed_lines = edocument._distribute_lines(lines_to_distribute, fpos, edocument.company_id, partner_id, self)
            for distributed_line in distributed_lines:
                order_lines.append((0, 0, distributed_line))

        # for distributed_line in distributed_lines:
        #     distributed_line.update({'date_planned': self.date_order})
        #     order_lines.append((0, 0, distributed_line))

        self.order_line = order_lines


    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        return orders

    def write(self, vals):
        result = super(PurchaseOrder, self).write(vals)
        return result

    def button_approve(self, force=False):
        result = super(PurchaseOrder, self).button_approve(force=force)
        print(result)
        return result


    def button_cancel(self):
        for order in self:
            pickings = order.picking_ids.filtered(lambda p: p.state == 'done')
            if pickings:
                for picking in pickings:
                    picking.action_cancel()
            for inv in order.invoice_ids:
                if inv and inv.state in ('posted'):
                    inv.with_context(force_delete=True).all_in_one_force_delete_invoice_and_related_payment()
        return super(PurchaseOrder, self).button_cancel()


    def _prepare_invoice(self):
        invoice_vals = super()._prepare_invoice()
        invoice_vals['invoice_date'] = self.date_order
        invoice_vals['l10n_latam_document_number'] = self.partner_ref
        invoice_vals['l10n_ec_authorization_number'] = self.origin
        invoice_vals['l10n_ec_sri_payment_id'] =self.env.ref('l10n_ec.P20').id
        invoice_vals['edocument_id'] = self.edocument_id.id
        return invoice_vals


class PurchaseOrderLine(models.Model):
    _inherit = ['purchase.order.line']

    edocument_line_id = fields.Many2one('edocument.line', 'Linea Documento Electronico', ondelete='set null', index='btree_not_null', copy=False)
    edocument_order_id = fields.Many2one('edocument', 'Documento Electronico', related='edocument_line_id.order_id', readonly=True)


    def _prepare_account_move_line(self, move=False):
        res = super()._prepare_account_move_line(move)
        res.update({'edocument_line_id': self.edocument_line_id.id})
        return res

    def _compute_price_unit_and_date_planned_and_name(self):
        po_lines_without_requisition = self.env['purchase.order.line']
        for pol in self:
            if pol.product_id.id not in pol.order_id.edocument_id.order_line.product_id.ids:
                po_lines_without_requisition |= pol
                continue
            for line in pol.order_id.edocument_id.order_line:
                if line.product_id == pol.product_id:
                    pol.discount = line.discount
                    break
        super(PurchaseOrderLine, po_lines_without_requisition)._compute_price_unit_and_date_planned_and_name()
