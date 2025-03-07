# Part of Odoo. See LICENSE file for full copyright and licensing details.
from datetime import datetime, time
from dateutil.relativedelta import relativedelta
from pytz import UTC

from odoo import _, api, fields, models, tools

from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT, get_lang
from odoo.tools.float_utils import float_compare, float_round
from odoo.exceptions import UserError


class ElectronicDocumentLine(models.Model):
    _name = 'edocument.line'
    _description = 'Lineas de Documento Electronico'
    _order = 'document_id, sequence, id'


    @tools.ormcache()
    def _get_default_uom_id(self):
        # Deletion forbidden (at least through unlink)
        return self.env.ref('uom.product_uom_unit')

    @tools.ormcache()
    def _get_default_category_id(self):
        return self.env.ref('product.product_category_1')
        # return self.env.ref('product.product_category_goods')


    def _read_group_categ_id(self, categories, domain):
        category_ids = self.env.context.get('default_categ_id')
        if not category_ids and self.env.context.get('group_expand'):
            category_ids = categories.sudo()._search([], order=categories._order)
        return categories.browse(category_ids)

    product_name = fields.Char('Nombre')
    product_code = fields.Char('Código')

    name = fields.Text(
        string='Descripcion')
    sequence = fields.Integer(string='secuencia', default=10)
    product_qty = fields.Float(string='Cantidad', digits='Product Unit of Measure', required=True,
                               compute='_compute_product_qty', store=True, readonly=False)
    product_uom_qty = fields.Float(string='Cantidad Total', compute='_compute_product_uom_qty', store=True)
    discount = fields.Float(
        string="Descuento (%)", digits='Discount',readonly=False)
    taxes_id = fields.Many2many('account.tax', string='Impuestos', context={'active_test': False})
    product_uom = fields.Many2one('uom.uom', string='Unidad de Medida' ,default=_get_default_uom_id)
    product_id = fields.Many2one('product.product', string='Producto', domain=[('purchase_ok', '=', True)], change_default=True, index='btree_not_null')
    product_type = fields.Selection(related='product_id.type', readonly=True)
    type = fields.Selection(
        string="Tipo",
        selection=[
            ('consu', "Producto"),
            ('service', "Servicio"),
        ],
        required=True,
        default='consu',
    )
    price_unit = fields.Float(
        string='Precio Unitario', required=True,  digits=(12,5), readonly=False)
    price_unit_discounted = fields.Float('Precio Unitario Neto', digits='Product Price', compute='_compute_price_unit_discounted')

    price_subtotal = fields.Float(compute='_compute_amount', string='Subtotal', digits='Product Price',aggregator=None, store=True)
    price_init = fields.Float(compute='_compute_amount', string='Costo',digits='Product Price', aggregator=None, store=True)
    price_discount = fields.Float(compute='_compute_amount', string='Descuento',digits='Product Price', aggregator=None, store=True)
    price_total = fields.Float(compute='_compute_amount', digits='Product Price', string='Total', store=True)
    price_tax = fields.Float(compute='_compute_amount', string='Impuestos', digits='Product Price', store=True)

    document_id = fields.Many2one('edocument', string='Documento Electronico', index=True, required=True, ondelete='cascade')

    company_id = fields.Many2one('res.company', related='document_id.company_id', string='Compania', store=True, readonly=True)
    state = fields.Selection(related='document_id.state', store=True)

    partner_id = fields.Many2one('res.partner', related='document_id.partner_id', string='Proveedor', readonly=True, store=True, index='btree_not_null')
    currency_id = fields.Many2one(related='document_id.currency_id', store=True, string='Moneda', readonly=True)
    fecha_emision = fields.Date(related='document_id.fecha_emision', string='Fecha Documento', readonly=True)
    l10n_ec_authorization_date = fields.Char(related="document_id.l10n_ec_authorization_date", string='Fecha Autorizacion', readonly=True)
    product_packaging_id = fields.Many2one('product.packaging', string='Packaging', domain="[('purchase', '=', True), ('product_id', '=', product_id)]", check_company=True,
                                           compute="_compute_product_packaging_id", store=True, readonly=False)
    product_packaging_qty = fields.Float('Packaging Quantity', compute="_compute_product_packaging_qty", store=True, readonly=False)
    tax_calculation_rounding_method = fields.Selection(
        related='company_id.tax_calculation_rounding_method',
        string='Tax calculation rounding method', readonly=True)
    vinculado = fields.Boolean(default=False)
    crear = fields.Boolean(default=False)
    unificar = fields.Boolean(default=False)
    distribuir = fields.Boolean(default=False)
    distribuir_code = fields.Char('Codigo producto para Distribución')
    # categ_id = fields.Many2one('product.category', 'Categoria',change_default=True, default=_get_default_category_id)

    categ_id = fields.Many2one(
        'product.category', 'Categoria',
        change_default=True, default=_get_default_category_id, group_expand='_read_group_categ_id',
        required=True)

    tipo_homologacion = fields.Selection(related='document_id.tipo_homologacion',
        string='Tipo de Homologación', readonly=True, copy=False, store=True)

    tracking = fields.Selection([
        ('serial', 'Serie'),
        # ('lot', 'By Lots'),
        ('none', 'No')],
        string="Tracking", required=True, default='none')

    purchase_lines = fields.One2many('purchase.order.line', 'edocument_line_id', string="Lineas de Compras", readonly=True, copy=False)
    invoice_lines = fields.One2many('account.move.line', 'edocument_line_id', string="Lineas de  Facturas", readonly=True, copy=False)

    uom_ids_allowed = fields.Many2many('uom.uom', compute='_compute_uom_ids_allowed', string='UdM Permitidos')

    @api.depends('product_id')
    def _compute_uom_ids_allowed(self):
        for line in self:
            if line.product_id:
                uom_records = line.product_id.sale_uom_ids
                if line.product_id.uom_id not in uom_records:
                    uom_records |= line.product_id.uom_id
                line.uom_ids_allowed = uom_records
            else:
                line.uom_ids_allowed = self.env['uom.uom']

    @api.onchange('product_id')
    def _compute_uom_ids_allowed_onchange(self):
        self._compute_uom_ids_allowed()


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
            partner_id=self.document_id.partner_id,
            currency_id=self.document_id.currency_id,
            # rate=self.document_id.currency_rate,
        )

    def _compute_tax_id(self):
        for line in self:
            line = line.with_company(line.company_id)
            fpos = line.document_id.fiscal_position_id or line.document_id.fiscal_position_id._get_fiscal_position(line.document_id.partner_id)
            # filter taxes by company
            taxes = line.product_id.supplier_taxes_id._filter_taxes_by_company(line.company_id)
            line.taxes_id = fpos.map_tax(taxes)

    @api.depends('discount', 'price_unit')
    def _compute_price_unit_discounted(self):
        for line in self:
            line.price_unit_discounted = line.price_unit * (1 - line.discount / 100)



    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            values.update(self._prepare_add_missing_fields(values))
        lines = super().create(vals_list)
        return lines

    def write(self, values):
        return super(ElectronicDocumentLine, self).write(values)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_purchase_or_done(self):
        for line in self:
            if line.document_id.state in ['purchase', 'invoice','cancel']:
                state_description = {state_desc[0]: state_desc[1] for state_desc in self._fields['state']._description_selection(self.env)}
                raise UserError(_('Cannot delete a purchase order line which is in state “%s”.', state_description.get(line.state)))



    @api.onchange('product_id')
    def onchange_product_id(self):
        if not self.product_id:
            self.vinculado=False
            return
        self.product_uom = self.product_id.uom_po_id or self.product_id.uom_id
        product_lang = self.product_id.with_context(
            lang=get_lang(self.env, self.partner_id.lang).code,
            partner_id=None,
            company_id=self.company_id.id)
        self.name = product_lang.display_name
        self.tracking = self.product_id.tracking
        self.type = self.product_id.type
        self.categ_id= self.product_id.categ_id.id
        self._compute_tax_id()


    @api.depends('product_id', 'product_qty', 'product_uom')
    def _compute_product_packaging_id(self):
        for line in self:
            # remove packaging if not match the product
            if line.product_packaging_id.product_id != line.product_id:
                line.product_packaging_id = False
            if line.product_id and line.product_qty and line.product_uom:
                suggested_packaging = line.product_id.packaging_ids\
                        .filtered(lambda p: p.purchase and (p.product_id.company_id <= p.company_id <= line.company_id))\
                        ._find_suitable_product_packaging(line.product_qty, line.product_uom)
                line.product_packaging_id = suggested_packaging or line.product_packaging_id


    @api.onchange('product_packaging_id')
    def _onchange_product_packaging_id(self):
        if self.product_packaging_id and self.product_qty:
            newqty = self.product_packaging_id._check_qty(self.product_qty, self.product_uom, "UP")
            if float_compare(newqty, self.product_qty, precision_rounding=self.product_uom.rounding) != 0:
                return {
                    'warning': {
                        'title': _('Warning'),
                        'message': _(
                            "This product is packaged by %(pack_size).2f %(pack_name)s. You should purchase %(quantity).2f %(unit)s.",
                            pack_size=self.product_packaging_id.qty,
                            pack_name=self.product_id.uom_id.name,
                            quantity=newqty,
                            unit=self.product_uom.name
                        ),
                    },
                }

    @api.depends('product_packaging_id', 'product_uom', 'product_qty')
    def _compute_product_packaging_qty(self):
        self.product_packaging_qty = 0
        for line in self:
            if not line.product_packaging_id:
                continue
            line.product_packaging_qty = line.product_packaging_id._compute_qty(line.product_qty, line.product_uom)

    @api.depends('product_packaging_qty')
    def _compute_product_qty(self):
        for line in self:
            if line.product_packaging_id:
                packaging_uom = line.product_packaging_id.product_uom_id
                qty_per_packaging = line.product_packaging_id.qty
                product_qty = packaging_uom._compute_quantity(line.product_packaging_qty * qty_per_packaging, line.product_uom)
                if float_compare(product_qty, line.product_qty, precision_rounding=line.product_uom.rounding) != 0:
                    line.product_qty = product_qty

    @api.depends('product_uom', 'product_qty', 'product_id.uom_id')
    def _compute_product_uom_qty(self):
        for line in self:
            if line.product_id and line.product_id.uom_id != line.product_uom:
                line.product_uom_qty = line.product_uom._compute_quantity(line.product_qty, line.product_id.uom_id)
            else:
                line.product_uom_qty = line.product_qty



    @api.model
    def _prepare_add_missing_fields(self, values):
        """ Deduce missing required fields from the onchange """
        res = {}
        onchange_fields = ['name', 'price_unit', 'product_qty', 'product_uom', 'taxes_id']
        if values.get('document_id') and values.get('product_id') and any(f not in values for f in onchange_fields):
            line = self.new(values)
            line.onchange_product_id()
            for field in onchange_fields:
                if field not in values:
                    res[field] = line._fields[field].convert_to_write(line[field], line)
        return res

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
                'product_uom':self.product_uom.id,
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
        fpos = self.document_id.fiscal_position_id or self.document_id.fiscal_position_id._get_fiscal_position(self.partner_id)
        sale_margin = (self.company_id.l10n_ec_edocument_sale_margin/100)+1 or 1.05
        if self.crear:
            vals ={
            'name':self.product_name,
            'default_code':self.product_code,
            'uom_id':self.env.ref('uom.product_uom_unit').id,
            'uom_po_id':self.product_uom.id,
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
        uom_po_qty = product_uom._compute_quantity(product_qty, product_uom or product_id.uom_po_id, rounding_method='HALF-UP')
        product_taxes = product_id.supplier_taxes_id.filtered(lambda x: x.company_id in company_id.parent_ids)
        taxes = po.fiscal_position_id.map_tax(product_taxes)
        price_unit = self.price_unit
        product_lang = product_id.with_prefetch().with_context(
            lang=partner.lang,
            partner_id=partner.id,
        )
        date_planned = self.document_id.fecha_emision or self._get_date_planned(partner, po=po)
        name = product_lang.display_name
        if product_lang.description_purchase:
            name += '\n' + product_lang.description_purchase
        return {
            'name': name,
            'product_qty': uom_po_qty,
            'product_id': product_id.id,
            'product_uom': product_uom.id or product_id.uom_po_id.id,
            'price_unit': price_unit,
            'date_planned': date_planned,
            'taxes_id': [(6, 0, taxes.ids)],
            'order_id': po.id,
            'discount': discount,
            'edocument_line_id':self.id,
        }

    @api.model
    def _prepare_purchase_order_line_from_unify(self, product_id, price_unit, product_qty, product_uom, discount,company_id, partner, po):
        uom_po_qty = product_uom._compute_quantity(product_qty,product_uom or product_id.uom_po_id, rounding_method='HALF-UP')
        product_taxes = product_id.supplier_taxes_id.filtered(lambda x: x.company_id in company_id.parent_ids)
        taxes = po.fiscal_position_id.map_tax(product_taxes)
        # price_unit = self.price_unit
        product_lang = product_id.with_prefetch().with_context(
            lang=partner.lang,
            partner_id=partner.id,
        )
        date_planned = self.document_id.fecha_emision or self._get_date_planned(partner, po=po)
        name = product_lang.display_name
        if product_lang.description_purchase:
            name += '\n' + product_lang.description_purchase
        return {
            'name': name,
            'product_qty': uom_po_qty,
            'product_id': product_id.id,
            'product_uom': product_uom.id or product_id.uom_po_id.id,
            'price_unit': price_unit,
            'date_planned': date_planned,
            'taxes_id': [(6, 0, taxes.ids)],
            'order_id': po.id,
            'discount': discount,
            'edocument_line_id':self.id,
        }
    def button_asignar_producto_linea(self):
        for rec in self:
            if rec.product_id:
                rec.crear_codes_prov_xml()
            else:
                raise UserError("Necesita seleccionar un producto para asignar")
