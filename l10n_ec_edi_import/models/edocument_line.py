# Part of Odoo. See LICENSE file for full copyright and licensing details.
from datetime import datetime, time
from dateutil.relativedelta import relativedelta
from pytz import UTC

from odoo import api, fields, models, tools, _
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT, get_lang
from odoo.tools.float_utils import float_compare, float_round
from odoo.exceptions import UserError


class ElectronicDocumentLine(models.Model):
    _name = 'edocument.line'
    _inherit = ['analytic.mixin']
    _description = 'Lineas de Documento Electronico'
    _order = 'order_id, sequence, id'


    @tools.ormcache()
    def _get_default_category_id(self):
        return self.env.ref('product.product_category_goods')

    product_name = fields.Char('Nombre')
    product_code = fields.Char('Código')

    name = fields.Text(string='Descripcion')
    sequence = fields.Integer(string='Sequence', default=10)
    product_qty = fields.Float(string='Quantity', digits='Product Unit', required=True)
    product_uom_qty = fields.Float(string='Total Quantity', compute='_compute_product_uom_qty', store=True)
    discount = fields.Float(
        string="Descuento (%)", digits='Discount',readonly=False)
    taxes_id = fields.Many2many('account.tax', string='Taxes', context={'active_test': False})
    allowed_uom_ids = fields.Many2many('uom.uom', compute='_compute_allowed_uom_ids')
    product_uom_id = fields.Many2one('uom.uom', string='Unit', domain="[('id', 'in', allowed_uom_ids)]")
    product_id = fields.Many2one('product.product', string='Product', domain=[('purchase_ok', '=', True)], change_default=True, index='btree_not_null', ondelete='restrict')
    product_type = fields.Selection(related='product_id.type', readonly=True)

    price_unit = fields.Float(
        string='Precio Unitario', required=True,  digits=(12,5), readonly=False)
    price_unit_discounted = fields.Float('Precio Unitario Neto', digits='Product Price', compute='_compute_price_unit_discounted')

    price_subtotal = fields.Float(compute='_compute_amount', string='Subtotal', digits='Product Price',aggregator=None, store=True)
    price_init = fields.Float(compute='_compute_amount', string='Costo',digits='Product Price', aggregator=None, store=True)
    price_discount = fields.Float(compute='_compute_amount', string='Descuento',digits='Product Price', aggregator=None, store=True)
    price_total = fields.Float(compute='_compute_amount', digits='Product Price', string='Total', store=True)
    price_tax = fields.Float(compute='_compute_amount', string='Impuestos', digits='Product Price', store=True)



    order_id = fields.Many2one('edocument', string='Order Reference', index=True, required=True, ondelete='cascade')

    company_id = fields.Many2one('res.company', related='order_id.company_id', string='Company', store=True, readonly=True)
    state = fields.Selection(related='order_id.state', store=True)


    # Replace by invoiced Qty
    qty_invoiced = fields.Float(compute='_compute_qty_invoiced', string="Billed Qty", digits='Product Unit', store=True)
    qty_to_invoice = fields.Float(compute='_compute_qty_invoiced', string='To Invoice Quantity', store=True, readonly=True,
                                  digits='Product Unit')

    qty_purchased = fields.Float(compute='_compute_qty_purchased', string="Cant. Compras", digits='Product Unit', store=True)
    qty_to_purchase = fields.Float(compute='_compute_qty_purchased', string='Cant. Pendiente', store=True, readonly=True,
                                  digits='Product Unit')


    partner_id = fields.Many2one('res.partner', related='order_id.partner_id', string='Partner', readonly=True, store=True, index='btree_not_null')
    currency_id = fields.Many2one(related='order_id.currency_id', string='Currency')
    date_order = fields.Datetime(related='order_id.date_order', string='Order Date', readonly=True)
    date_approve = fields.Datetime(related="order_id.date_approve", string='Confirmation Date', readonly=True)
    tax_calculation_rounding_method = fields.Selection(
        related='company_id.tax_calculation_rounding_method',
        string='Tax calculation rounding method', readonly=True)
    display_type = fields.Selection([
        ('line_section', "Section"),
        ('line_note', "Note")], default=False, help="Technical field for UX purpose.")
    is_downpayment = fields.Boolean()

    _accountable_required_fields = models.Constraint(
        'CHECK(display_type IS NOT NULL OR is_downpayment OR (product_id IS NOT NULL AND product_uom_id IS NOT NULL))',
        'Missing required fields on accountable purchase order line.',
    )
    _non_accountable_null_fields = models.Constraint(
        'CHECK(display_type IS NULL OR (product_id IS NULL AND price_unit = 0 AND product_uom_qty = 0 AND product_uom_id IS NULL))',
        'Forbidden values on non-accountable purchase order line',
    )
    product_template_attribute_value_ids = fields.Many2many(related='product_id.product_template_attribute_value_ids', readonly=True)
    product_no_variant_attribute_value_ids = fields.Many2many('product.template.attribute.value', string='Product attribute values that do not create variants', ondelete='restrict')


    vinculado = fields.Boolean(default=False)
    crear = fields.Boolean(default=False)
    unificar = fields.Boolean(default=False)
    distribuir = fields.Boolean(default=False)
    distribuir_code = fields.Char('Codigo producto para Distribución')

    type = fields.Selection(
        string="Tipo",
        selection=[
            ('consu', "Bien"),
            ('service', "Servicio"),
        ],
        required=True,
        default='consu',

    )

    categ_id = fields.Many2one(
        string="Categoria",
        comodel_name='product.category',
        default=_get_default_category_id,
        group_expand='_read_group_categ_id',
    )

    tipo_homologacion = fields.Selection(related='order_id.tipo_homologacion',
        string='Tipo de Homologación', readonly=True, copy=False, store=True)

    tracking = fields.Selection([
        ('serial', 'Serie'),
        # ('lot', 'By Lots'),
        ('none', 'No')],
        string="Tracking", required=True, default='none')

    purchase_lines = fields.One2many('purchase.order.line', 'edocument_line_id', string="Lineas de Compras", readonly=True, copy=False)
    invoice_lines = fields.One2many('account.move.line', 'edocument_line_id', string="Lineas de  Facturas", readonly=True, copy=False)


    def button_crear_producto_desde_linea(self):
        self.ensure_one()
        for rec in self:
            supplier_code= rec.verifica_codes_supplier_prov_xml(rec.product_code, rec.partner_id.id)
            product_code= rec.verifica_codes_prod_prov_xml(rec.product_code)
            if supplier_code:
                rec.product_id=supplier_code.product_id
            elif product_code:
                rec.product_id=product_code.id
            else:
                rec.crear= True
                rec.crear_productos_xml()
            # if rec.product_id:
            #     rec.compra_id.update({'product_id':rec.product_id.id})




    def verifica_codes_supplier_prov_xml(self,product_code, partner_id):
        mcode = None
        mcode = self.env['edocument.product.supplier'].search([
            ('partner_id', '=', partner_id),
            ('product_code', '=', product_code)
            ], limit=1)
        return mcode

    def verifica_codes_prod_prov_xml(self,product_code):
        mcode = None
        mcode = self.env['product.product'].search([
            ('default_code', '=', product_code)
            ], limit=1)
        return mcode


    def crear_codes_prov_xml(self):
        mcode = None
        mcode = self.env['edocument.product.supplier'].search([
            ('partner_id', '=', self.partner_id.id),
            ('product_code', '=', self.product_code)
            ], limit=1)

        if mcode:
            if not mcode.product_id==self.product_id:
                mcode = None
            if mcode:
                mcode.write({'unificar':self.unificar,'distribuir':self.distribuir,'distribuir_code':self.distribuir_code})
        if not mcode:
            if self.product_id:
                vals_codes={
                'partner_id':self.partner_id.id,
                'product_name':self.product_name,
                'product_code':self.product_code,
                'product_uom_id':self.product_uom_id.id,
                'product_id':self.product_id.id,
                'product_tmpl_id':self.product_id.product_tmpl_id.id,
                'unificar':self.unificar,
                'distribuir':self.distribuir,
                'distribuir_code':self.distribuir_code,
                }
                mcode = self.env['edocument.product.supplier'].create(vals_codes)
                self.crear=False
        return mcode

    def crear_productos_xml(self):
        self.ensure_one()
        mproducto = False
        tax_id = self.company_id.l10n_ec_edocument_goods_sale_tax_id
        fpos = self.order_id.fiscal_position_id or self.order_id.fiscal_position_id._get_fiscal_position(self.partner_id)
        sale_margin = (self.company_id.l10n_ec_edocument_sale_margin/100)+1 or 1.05
        if self.crear:
            vals ={
            'name':self.product_name,
            'default_code':self.product_code,
            'uom_id':self.env.ref('uom.product_uom_unit').id,
            'list_price':self.price_unit*sale_margin,
            'categ_id':self.categ_id.id,
            'standard_price':self.price_unit,
            'type':self.type,
            'purchase_ok':True,
            'sale_ok':True,
            'is_storable':False,
            'tracking':self.tracking,
            'taxes_id': fpos.map_tax(tax_id)
            }
            if self.type or self.type == 'consu':
                vals['is_storable']=True
            vals['supplier_taxes_id'] = self.taxes_id #[( 6, 0, self.supplier_taxes_id.ids)]
            mproducto = self.env['product.product'].create(vals)
            self.product_id=mproducto.id
            if mproducto:
                self.crear_codes_prov_xml()
        return mproducto


    def button_asignar_producto_linea(self):
        for rec in self:
            if rec.product_id:
                rec.crear_codes_prov_xml()
            else:
                raise UserError("Necesita seleccionar un producto para asignar")


    @api.depends('product_qty', 'price_unit', 'taxes_id', 'discount')
    def _compute_amount(self):
        for line in self:
            base_line = line._prepare_base_line_for_taxes_computation()
            line.price_discount = (line.price_unit - line.price_unit_discounted) * line.product_qty
            line.price_init = line.price_unit * line.product_qty
            self.env['account.tax']._add_tax_details_in_base_line(base_line, line.company_id)
            line.price_subtotal = base_line['tax_details']['raw_total_excluded_currency']
            line.price_total = base_line['tax_details']['raw_total_included_currency']
            # line.price_subtotal = base_line['tax_details']['total_excluded_currency']
            # line.price_total = base_line['tax_details']['total_included_currency']
            line.price_tax = line.price_total - line.price_subtotal


    def _prepare_base_line_for_taxes_computation(self):
        """ Convert the current record to a dictionary in order to use the generic taxes computation method
        defined on account.tax.

        :return: A python dictionary.
        """
        self.ensure_one()
        return self.env['account.tax']._prepare_base_line_for_taxes_computation(
            self,
            tax_ids=self.taxes_id,
            quantity=self.product_qty,
            partner_id=self.order_id.partner_id,
            currency_id=self.order_id.currency_id or self.order_id.company_id.currency_id,
        )


    def _compute_tax_id(self):
        for line in self:
            line = line.with_company(line.company_id)
            fpos = line.order_id.fiscal_position_id or line.order_id.fiscal_position_id._get_fiscal_position(line.order_id.partner_id)
            # filter taxes by company
            taxes = line.product_id.supplier_taxes_id._filter_taxes_by_company(line.company_id)
            line.taxes_id = fpos.map_tax(taxes)

    @api.depends('discount', 'price_unit')
    def _compute_price_unit_discounted(self):
        for line in self:
            line.price_unit_discounted = line.price_unit * (1 - line.discount / 100)

    @api.depends('invoice_lines.move_id.state', 'invoice_lines.quantity', 'product_uom_qty', 'order_id.state','product_qty')
    def _compute_qty_invoiced(self):
        for line in self:
            # compute qty_invoiced
            qty = 0.0
            for inv_line in line._get_invoice_lines():
                print(inv_line)
                if inv_line.move_id.state not in ['cancel'] or inv_line.move_id.payment_state == 'invoicing_legacy':
                    if inv_line.move_id.move_type == 'in_invoice':
                        qty += inv_line.product_uom_id._compute_quantity(inv_line.quantity, line.product_uom_id)
                    elif inv_line.move_id.move_type == 'in_refund':
                        qty -= inv_line.product_uom_id._compute_quantity(inv_line.quantity, line.product_uom_id)
            line.qty_invoiced = qty

            # compute qty_to_invoice
            if line.order_id.state in ['draft','sent','purchase','invoice', 'done']:
                line.qty_to_invoice = line.product_qty - line.qty_invoiced
            else:
                line.qty_to_invoice = 0

    def _get_invoice_lines(self):
        self.ensure_one()
        if self._context.get('accrual_entry_date'):
            print('accrual_entry_date')
            return self.invoice_lines.filtered(
                lambda l: l.move_id.invoice_date and l.move_id.invoice_date <= self._context['accrual_entry_date']
            )
        else:
            return self.invoice_lines

    def get_have_procesed_lines(self):
        invoice_lines = 0
        purchase_lines = 0
        for line in self:
            if line.type=='service':
                purchase_lines = 1
            else:
                purchase_lines = len(line.purchase_lines)
            invoice_lines=len(line.invoice_lines)
        return purchase_lines+purchase_lines


    @api.depends('purchase_lines.order_id.state', 'purchase_lines.product_qty',  'product_uom_qty', 'order_id.state','product_qty')
    def _compute_qty_purchased(self):
        for line in self:
            qty = 0.0
            if line.type=='service':
                qty = line.product_uom_id._compute_quantity(line.product_qty, line.product_uom_id)

            for inv_line in line._get_orderedlines():
                if inv_line.order_id.state not in ['cancel']:
                    qty += inv_line.product_uom_id._compute_quantity(inv_line.product_qty, line.product_uom_id)
            line.qty_purchased = qty
            if line.order_id.state in ['sent','purchase','invoice', 'done']:
                line.qty_to_purchase = line.product_qty - line.qty_purchased
            else:
                line.qty_to_purchase = 0


    def _get_orderedlines(self):
        self.ensure_one()
        return self.purchase_lines


    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if values.get('display_type', self.default_get(['display_type'])['display_type']):
                values.update(product_id=False, price_unit=0, product_uom_qty=0, product_uom_id=False)
            else:
                values.update(self._prepare_add_missing_fields(values))

        lines = super().create(vals_list)
        for line in lines:
            if line.product_id and line.order_id.state == 'purchase':
                msg = _("Extra line with %s ", line.product_id.display_name)
                line.order_id.message_post(body=msg)
        return lines

    def write(self, values):
        if 'display_type' in values and self.filtered(lambda line: line.display_type != values.get('display_type')):
            raise UserError(_("You cannot change the type of a purchase order line. Instead you should delete the current line and create a new line of the proper type."))

        if 'product_qty' in values:
            precision = self.env['decimal.precision'].precision_get('Product Unit')
            for line in self:
                if (
                    line.order_id.state == "purchase"
                    and float_compare(line.product_qty, values["product_qty"], precision_digits=precision) != 0
                ):
                    line.order_id.message_post_with_source(
                        'purchase.track_po_line_template',
                        render_values={'line': line, 'product_qty': values['product_qty']},
                        subtype_xmlid='mail.mt_note',
                    )
        return super(ElectronicDocumentLine, self).write(values)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_purchase_or_done(self):
        for line in self:
            if line.order_id.state in ['purchase', 'done']:
                state_description = {state_desc[0]: state_desc[1] for state_desc in self._fields['state']._description_selection(self.env)}
                raise UserError(_('Cannot delete a purchase order line which is in state “%s”.', state_description.get(line.state)))



    @api.depends('product_id', 'order_id.partner_id')
    def _compute_analytic_distribution(self):
        for line in self:
            if not line.display_type:
                distribution = self.env['account.analytic.distribution.model']._get_distribution({
                    "product_id": line.product_id.id,
                    "product_categ_id": line.product_id.categ_id.id,
                    "partner_id": line.order_id.partner_id.id,
                    "partner_category_id": line.order_id.partner_id.category_id.ids,
                    "company_id": line.company_id.id,
                })
                line.analytic_distribution = distribution or line.analytic_distribution

    @api.onchange('product_id')
    def onchange_product_id(self):
        # TODO: Remove when onchanges are replaced with computes
        if not self.product_id or (self.env.context.get('origin_po_id') and self.product_qty):
            return

        # Reset date, price and quantity since _onchange_quantity will provide default values
        self.price_unit = self.product_qty = 0.0

        self._product_id_change()

        self._suggest_quantity()

    def _product_id_change(self):
        if not self.product_id:
            return

        self.product_uom_id = self.product_id.uom_id
        product_lang = self.product_id.with_context(
            lang=get_lang(self.env, self.partner_id.lang).code,
            partner_id=None,
            company_id=self.company_id.id,
        )
        self.name = self._get_product_purchase_description(product_lang)

        self._compute_tax_id()

    @api.onchange('product_id')
    def onchange_product_id_warning(self):
        if not self.product_id or not self.env.user.has_group('purchase.group_warning_purchase'):
            return
        warning = {}
        title = False
        message = False

        product_info = self.product_id

        if product_info.purchase_line_warn != 'no-message':
            title = _("Warning for %s", product_info.name)
            message = product_info.purchase_line_warn_msg
            warning['title'] = title
            warning['message'] = message
            if product_info.purchase_line_warn == 'block':
                self.product_id = False
            return {'warning': warning}
        return {}

    @api.depends('product_id', 'product_id.uom_id', 'product_id.uom_ids', 'product_id.seller_ids', 'product_id.seller_ids.product_uom_id')
    def _compute_allowed_uom_ids(self):
        for line in self:
            line.allowed_uom_ids = line.product_id.uom_id | line.product_id.uom_ids | line.product_id.seller_ids.product_uom_id

    @api.depends('product_id')
    def _compute_product_uom_id(self):
        for line in self:
            line.product_uom_id = line.product_id.seller_ids.filtered(lambda s: s.partner_id == line.partner_id).product_uom_id or line.product_id.uom_id if line.product_id else False

    @api.depends('product_uom_id', 'product_qty', 'product_id.uom_id')
    def _compute_product_uom_qty(self):
        for line in self:
            if line.product_id and line.product_id.uom_id != line.product_uom_id:
                line.product_uom_qty = line.product_uom_id._compute_quantity(line.product_qty, line.product_id.uom_id)
            else:
                line.product_uom_qty = line.product_qty

    def _get_gross_price_unit(self):
        self.ensure_one()
        price_unit = self.price_unit
        if self.discount:
            price_unit = price_unit * (1 - self.discount / 100)
        if self.taxes_id:
            qty = self.product_qty or 1
            price_unit = self.taxes_id.compute_all(
                price_unit,
                currency=self.order_id.currency_id,
                quantity=qty,
                rounding_method='round_globally',
            )['total_void']
            price_unit = price_unit / qty
        if self.product_uom_id.id != self.product_id.uom_id.id:
            price_unit *= self.product_id.uom_id.factor / self.product_uom_id.factor
        return price_unit

    def action_add_from_catalog(self):
        order = self.env['edocument'].browse(self.env.context.get('order_id'))
        return order.with_context(child_field='order_line').action_add_from_catalog()

    def action_edocument_history(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("purchase.action_purchase_history")
        action['domain'] = [('state', 'in', ['purchase', 'done']), ('product_id', '=', self.product_id.id)]
        action['display_name'] = _("Purchase History for %s", self.product_id.display_name)
        action['context'] = {
            'search_default_partner_id': self.partner_id.id
        }

        return action

    def _suggest_quantity(self):
        '''
        Suggest a minimal quantity based on the seller
        '''
        if not self.product_id:
            return
        seller_min_qty = self.product_id.seller_ids\
            .filtered(lambda r: r.partner_id == self.order_id.partner_id and (not r.product_id or r.product_id == self.product_id))\
            .sorted(key=lambda r: r.min_qty)
        if seller_min_qty:
            self.product_qty = seller_min_qty[0].min_qty or 1.0
            self.product_uom_id = seller_min_qty[0].product_uom_id
        else:
            self.product_qty = 1.0

    def _get_product_catalog_lines_data(self, **kwargs):
        """ Return information about purchase order lines in `self`.

        If `self` is empty, this method returns only the default value(s) needed for the product
        catalog. In this case, the quantity that equals 0.

        Otherwise, it returns a quantity and a price based on the product of the POL(s) and whether
        the product is read-only or not.

        A product is considered read-only if the order is considered read-only (see
        ``PurchaseOrder._is_readonly`` for more details) or if `self` contains multiple records
        or if it has purchase_line_warn == "block".

        Note: This method cannot be called with multiple records that have different products linked.

        :raise odoo.exceptions.ValueError: ``len(self.product_id) != 1``
        :rtype: dict
        :return: A dict with the following structure:
            {
                'quantity': float,
                'price': float,
                'readOnly': bool,
                'uom': dict,
                'purchase_uom': dict,
                'packaging': dict,
                'warning': String,
            }
        """
        if len(self) == 1:
            catalog_info = self.order_id._get_product_price_and_data(self.product_id)
            uom = {
                'display_name': self.product_id.uom_id.display_name,
                'id': self.product_id.uom_id.id,
            }
            catalog_info.update(
                quantity=self.product_qty,
                price=self.price_unit * (1 - self.discount / 100),
                readOnly=self.order_id._is_readonly(),
                uom=uom,
            )
            if self.product_id.uom_id != self.product_uom_id:
                catalog_info['purchase_uom'] = {
                'display_name': self.product_uom_id.display_name,
                'id': self.product_uom_id.id,
            }
            return catalog_info
        elif self:
            self.product_id.ensure_one()
            order_line = self[0]
            catalog_info = order_line.order_id._get_product_price_and_data(order_line.product_id)
            catalog_info['quantity'] = sum(self.mapped(
                lambda line: line.product_uom_id._compute_quantity(
                    qty=line.product_qty,
                    to_unit=line.product_id.uom_id,
            )))
            catalog_info['readOnly'] = True
            return catalog_info
        return {'quantity': 0}

    def _get_product_purchase_description(self, product_lang):
        self.ensure_one()
        name = product_lang.display_name
        if product_lang.description_purchase:
            name += '\n' + product_lang.description_purchase

        return name

    def _prepare_account_move_line(self, move=False):
        self.ensure_one()
        aml_currency = move and move.currency_id or self.currency_id
        date = move and move.date or fields.Date.today()

        res = {
            'display_type': self.display_type or 'product',
            # 'name': self.env['account.move.line']._get_journal_items_full_name(self.name, self.product_id.display_name),
            'name': f"{self.product_id.display_name} {self.name}",
            'product_id': self.product_id.id,
            'product_uom_id': self.product_uom_id.id,
            'quantity': self.qty_to_invoice,
            'discount': self.discount,
            'price_unit': self.currency_id._convert(self.price_unit, aml_currency, self.company_id, date, round=False),
            'tax_ids': [(6, 0, self.taxes_id.ids)],
            'edocument_line_id': self.id,
            'is_downpayment': self.is_downpayment,
        }
        if self.analytic_distribution and not self.display_type:
            res['analytic_distribution'] = self.analytic_distribution
        return res

    @api.model
    def _prepare_add_missing_fields(self, values):
        """ Deduce missing required fields from the onchange """
        res = {}
        onchange_fields = ['name', 'price_unit', 'product_qty', 'product_uom_id', 'taxes_id']
        if values.get('order_id') and values.get('product_id') and any(f not in values for f in onchange_fields):
            line = self.new(values)
            line.onchange_product_id()
            for field in onchange_fields:
                if field not in values:
                    res[field] = line._fields[field].convert_to_write(line[field], line)
        return res


    @api.model
    def _get_date_planned(self, seller, po=False):
        """Return the datetime value to use as Schedule Date (``date_planned``) for
           PO Lines that correspond to the given product.seller_ids,
           when ordered at `date_order_str`.

           :param Model seller: used to fetch the delivery delay (if no seller
                                is provided, the delay is 0)
           :param Model po: purchase.order, necessary only if the PO line is
                            not yet attached to a PO.
           :rtype: datetime
           :return: desired Schedule Date for the PO line
        """
        date_order = po.date_order if po else self.order_id.date_order
        if date_order:
            return date_order + relativedelta(days=seller.delay if seller else 0)
        else:
            return datetime.today() + relativedelta(days=seller.delay if seller else 0)

    @api.model
    def _prepare_purchase_order_line(self, product_id, product_qty, product_uom, discount,company_id, partner, po):
        uom_po_qty = product_uom._compute_quantity(product_qty, product_uom or product_id.uom_id, rounding_method='HALF-UP')
        product_taxes = product_id.supplier_taxes_id.filtered(lambda x: x.company_id in company_id.parent_ids)
        taxes = po.fiscal_position_id.map_tax(product_taxes)
        price_unit = self.price_unit
        product_lang = product_id.with_prefetch().with_context(
            lang=partner.lang,
            partner_id=partner.id,
        )
        date_planned = self.order_id.fecha_emision or self._get_date_planned(partner, po=po)
        name = product_lang.display_name
        if product_lang.description_purchase:
            name += '\n' + product_lang.description_purchase
        return {
            'name': name,
            'product_qty': uom_po_qty,
            'product_id': product_id.id,
            'product_uom_id': product_uom.id or product_id.uom_id.id,
            'price_unit': price_unit,
            'date_planned': date_planned,
            'taxes_id': [(6, 0, taxes.ids)],
            'order_id': po.id,
            'discount': discount,
            'edocument_line_id':self.id,
        }


    def _convert_to_middle_of_day(self, date):
        """Return a datetime which is the noon of the input date(time) according
        to order user's time zone, convert to UTC time.
        """
        return self.order_id.get_order_timezone().localize(datetime.combine(date, time(12))).astimezone(UTC).replace(tzinfo=None)


    def _validate_analytic_distribution(self):
        for line in self:
            if line.display_type:
                continue
            line._validate_distribution(
                product=line.product_id.id,
                business_domain='purchase_order',
                company_id=line.company_id.id,
            )

    def action_open_order(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'edocument',
            'res_id': self.order_id.id,
            'view_mode': 'form',
        }

    def _merge_po_line(self, rfq_line):
        self.product_qty += rfq_line.product_qty
        self.price_unit = min(self.price_unit, rfq_line.price_unit)

    def _get_select_sellers_params(self):
        self.ensure_one()
        return {
            "order_id": self.order_id,
        }
