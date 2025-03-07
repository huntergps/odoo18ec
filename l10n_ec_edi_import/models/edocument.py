# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
from collections import defaultdict
from datetime import datetime
from dateutil.relativedelta import relativedelta
from pytz import timezone

from markupsafe import escape, Markup
from werkzeug.urls import url_encode

from odoo import api, Command, fields, models, _
from odoo.osv import expression
# from odoo.tools import format_amount, format_date, format_list, formatLang, groupby
from odoo.tools.float_utils import float_is_zero
from odoo.exceptions import UserError, ValidationError



import xmltodict
import json

from odoo.tools import format_amount, format_date, format_list, formatLang, groupby,float_compare,float_repr,float_round,html_escape
from odoo.tools.xml_utils import cleanup_xml_node
from requests.exceptions import ConnectionError as RConnectionError
from odoo.tools.zeep import Client, Settings, Transport
import requests
from odoo.tools.zeep.exceptions import Error as ZeepError
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT as DTF




TEST_URL = {
    'reception': 'https://celcer.sri.gob.ec/comprobantes-electronicos-ws/RecepcionComprobantesOffline?wsdl',
    'authorization': 'https://celcer.sri.gob.ec/comprobantes-electronicos-ws/AutorizacionComprobantesOffline?wsdl',
}

PRODUCTION_URL = {
    'reception': 'https://cel.sri.gob.ec/comprobantes-electronicos-ws/RecepcionComprobantesOffline?wsdl',
    'authorization': 'https://cel.sri.gob.ec/comprobantes-electronicos-ws/AutorizacionComprobantesOffline?wsdl',
}

DEFAULT_TIMEOUT_WS = 20


def calcular_total_impuestos_por_tarifa(totalConImpuestos):
    tarifas_iva = {
        '0': 'IVA_0',
        '2': 'IVA_12',
        '3': 'IVA_14',
        '4': 'IVA_15',
        '5': 'IVA_5',
        '6': 'IVA_NO_OBJETO',
        '7': 'IVA_EXENTO',
        '8': 'IVA_8',
        '10': 'IVA_13'
    }

    tarifas_ice = {
        '3011': 'ICE3011',
        '3021': 'ICE3021',
        '3023': 'ICE3023',
        '3031': 'ICE3031',
        '3041': 'ICE3041',
        '3073': 'ICE3073',
        '3101': 'ICE3101',
        '3053': 'ICE3053',
        '3680': 'ICE3680'
    }

    irbpnr_code = '5'

    # Inicializar acumuladores de impuestos para cada tarifa
    totales_impuestos = {
        'IVA': {},
        'ICE': {},
        'IRBPNR': 0
    }

    # Verificar si totalConImpuestos es un diccionario único y convertirlo a lista
    if isinstance(totalConImpuestos['totalImpuesto'], dict):
        totalConImpuestos = [totalConImpuestos['totalImpuesto']]
    else:
        totalConImpuestos = totalConImpuestos['totalImpuesto']

    for impuesto in totalConImpuestos:
        codigo_impuesto = impuesto.get('codigo')
        codigo_porcentaje = impuesto.get('codigoPorcentaje')
        valor = impuesto.get('valor', 0)  # Si valor no existe, asignar 0

        try:
            valor = float(valor)
        except (ValueError, TypeError):
            valor = 0  # Si no puede convertirse a float, asignar 0

        # Calcular IVA
        if codigo_impuesto == '2' and codigo_porcentaje in tarifas_iva:
            nombre_iva = tarifas_iva[codigo_porcentaje]
            if nombre_iva not in totales_impuestos['IVA']:
                totales_impuestos['IVA'][nombre_iva] = 0
            totales_impuestos['IVA'][nombre_iva] += valor

        # Calcular ICE
        elif codigo_impuesto == '3' and codigo_porcentaje in tarifas_ice:
            nombre_ice = tarifas_ice[codigo_porcentaje]
            if nombre_ice not in totales_impuestos['ICE']:
                totales_impuestos['ICE'][nombre_ice] = 0
            totales_impuestos['ICE'][nombre_ice] += valor

        # Calcular IRBPNR
        elif codigo_impuesto == irbpnr_code:
            totales_impuestos['IRBPNR'] += valor

    return totales_impuestos

def obtener_valor_iva(totales_impuestos, tipo_iva):
    return totales_impuestos['IVA'].get(tipo_iva, 0.0)


class ElectronicDocument(models.Model):
    _name = 'edocument'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Documento Electronico"
    _rec_names_search = ['name', 'partner_ref']
    _order = 'priority desc, id desc'

    def _get_default_state_purchase_orders(self):
        company_id = self.company_id.id or self.env.company
        return company_id.l10n_ec_edocument_state_orders

    def exist_same_name(self,name):
        domain=[('name','=',name)]
        hay = self.env['edocument'].search(domain)
        estan = hay-self
        data = (estan and estan[0]) or False
        return data

    @api.depends('order_line.price_subtotal', 'company_id')
    def _amount_all(self):
        AccountTax = self.env['account.tax']
        for order in self:
            order_lines = order.order_line.filtered(lambda x: not x.display_type)
            base_lines = [line._prepare_base_line_for_taxes_computation() for line in order_lines]

            total_descuento = sum(line.price_discount for line in order_lines)
            subtotal = sum(line.price_init for line in order_lines)

            AccountTax._add_tax_details_in_base_lines(base_lines, order.company_id)
            AccountTax._round_base_lines_tax_details(base_lines, order.company_id)
            tax_totals = AccountTax._get_tax_totals_summary(
                base_lines=base_lines,
                currency=order.currency_id or order.company_id.currency_id,
                company=order.company_id,
            )
            order.amount_untaxed = tax_totals['base_amount_currency']
            order.amount_tax = tax_totals['tax_amount_currency']
            order.amount_total = tax_totals['total_amount_currency']

            order.amount_discount = total_descuento
            order.amount_subtotal = subtotal

    def get_procesed_lines(self):
        val=0.0
        for order in self:
            for line in  order.order_line:
                val += line.get_have_procesed_lines()
        print('val  :  ',val)
        return val>0

    @api.depends('state', 'order_line.qty_to_invoice','order_line.qty_to_purchase')
    def _get_invoiced(self):
        precision = self.env['decimal.precision'].precision_get('Product Unit')
        for order in self:
            if order.state not in ('sent','purchase', 'done','invoice'):
                order.invoice_status = 'no'
                continue
            print("-"*70)
            alguno=any(
                not float_is_zero(line.qty_to_invoice+line.qty_to_purchase, precision_digits=precision)
                for line in order.order_line.filtered(lambda l: not l.display_type)
            )
            todo=all(
                float_is_zero(line.qty_to_invoice+line.qty_to_purchase, precision_digits=precision)
                for line in order.order_line.filtered(lambda l: not l.display_type)
            )
            print('alguno:  ',alguno, '    todo: ',todo,' order.invoice_ids: ',order.invoice_ids,'  order.purchase_ids: ',order.purchase_ids)
            print(todo and order.get_procesed_lines() )
            print("-"*70)

            # if any(
            #     not float_is_zero(line.qty_to_invoice+line.qty_to_purchase, precision_digits=precision)
            #     for line in order.order_line.filtered(lambda l: not l.display_type)
            # ):
            if alguno:
                if (all(
                    float_is_zero(line.qty_to_purchase, precision_digits=precision)
                    for line in order.order_line.filtered(lambda l: not l.display_type)
                )):
                    order.state = 'purchase'
                else:
                    order.state = 'sent'

                order.invoice_status = 'to invoice'

                print("AGLUNO TIENE qty_to_invoice+qty_to_purchase")
            elif (
                todo and order.get_procesed_lines()
                # all(
                #     float_is_zero(line.qty_to_invoice+line.qty_to_purchase, precision_digits=precision)
                #     for line in order.order_line.filtered(lambda l: not l.display_type)
                # )
                # todo and order.invoice_ids # and order.purchase_ids
            ):
                order.invoice_status = 'invoiced'
                order.state = 'invoice'                
                print("TODO y invoice_ids y invoice_ids")
            else:
                order.invoice_status = 'no'
                order.state = 'sent'
                print("NO CUMPLE ALGUNO, TODO")


    @api.depends('order_line.invoice_lines.move_id')
    def _compute_invoice(self):
        for order in self:
            invoices = order.mapped('order_line.invoice_lines.move_id')
            order.invoice_ids = invoices
            order.invoice_count = len(invoices)

    name = fields.Char('Autorizacion', required=True, index='trigram', copy=False)
    priority = fields.Selection(
        [('0', 'Normal'), ('1', 'Urgente')], 'Prioridad', default='0', index=True)
    partner_ref = fields.Char('Vendor Reference', copy=False,
        help="Reference of the sales order or bid sent by the vendor. "
             "It's used to do the matching when you receive the "
             "products as this reference is usually written on the "
             "delivery order sent by your vendor.")
    date_order = fields.Datetime('Order Deadline', required=True, index=True, copy=False, default=fields.Datetime.now,
        help="Depicts the date within which the Quotation should be confirmed and converted into a purchase order.")
    date_approve = fields.Datetime('Confirmation Date', readonly=True, index=True, copy=False)
    partner_id = fields.Many2one('res.partner', string='Vendor', change_default=True, tracking=True, check_company=True, help="You can find a vendor by its Name, TIN, Email or Internal Reference.")
    currency_id = fields.Many2one('res.currency', 'Currency', required=True,
        default=lambda self: self.env.company.currency_id.id)

    order_line = fields.One2many('edocument.line', 'order_id', string='Order Lines', copy=True)
    notes = fields.Html('Notas')

    partner_bill_count = fields.Integer(related='partner_id.supplier_invoice_count')
    invoice_count = fields.Integer(compute="_compute_invoice", string='Bill Count', copy=False, default=0, store=True)
    invoice_ids = fields.Many2many('account.move', compute="_compute_invoice", string='Bills', copy=False, store=True)

    invoice_status = fields.Selection([
        ('no', 'Nada por Procesar'),
        ('to invoice', 'Pendiente'),
        ('invoiced', 'Procesado'),
    ], string='Proceso', compute='_get_invoiced', store=True, readonly=True, copy=False, default='no')

    date_calendar_start = fields.Datetime(compute='_compute_date_calendar_start', readonly=True, store=True)

    amount_untaxed = fields.Monetary(string='Untaxed Amount', store=True, readonly=True, compute='_amount_all', tracking=True)
    tax_totals = fields.Binary(compute='_compute_tax_totals', exportable=False)
    amount_tax = fields.Monetary(string='Taxes', store=True, readonly=True, compute='_amount_all')
    amount_total = fields.Monetary(string='Total', store=True, readonly=True, compute='_amount_all')

    amount_subtotal = fields.Monetary(string='SubTotal', store=True, readonly=True, compute='_amount_all')
    amount_discount = fields.Monetary(string='Descuento', store=True, readonly=True, compute='_amount_all')

    fiscal_position_id = fields.Many2one('account.fiscal.position', string='Fiscal Position', domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]")
    tax_country_id = fields.Many2one(
        comodel_name='res.country',
        compute='_compute_tax_country_id',
        # Avoid access error on fiscal position, when reading a purchase order with company != user.company_ids
        compute_sudo=True,
        help="Technical field to filter the available taxes depending on the fiscal country and fiscal position.")
    tax_calculation_rounding_method = fields.Selection(
        related='company_id.tax_calculation_rounding_method',
        string='Tax calculation rounding method', readonly=True)
    payment_term_id = fields.Many2one('account.payment.term', 'Payment Terms', domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]")

    product_id = fields.Many2one('product.product', related='order_line.product_id', string='Product')
    user_id = fields.Many2one(
        'res.users', string='Buyer', index=True, tracking=True,
        default=lambda self: self.env.user, check_company=True)
    company_id = fields.Many2one('res.company', 'Company', required=True, index=True, default=lambda self: self.env.company.id)
    company_currency_id = fields.Many2one(related="company_id.currency_id", string="Company Currency")
    country_code = fields.Char(related='company_id.account_fiscal_country_id.code', string="Country code")
    company_price_include = fields.Selection(related='company_id.account_price_include')


    ###############################################################################################################
    email = fields.Char(string='Correo Electrónico' ,related='partner_id.email', store=True)
    estado_sri = fields.Selection([
        ('NO ENVIADO', 'NO ENVIADO'),  # Documentos fuera de línea.
        ('RECIBIDA', 'RECIBIDA'),
        ('EN PROCESO', 'EN PROCESO'),
        ('DEVUELTA', 'DEVUELTA'),
        ('AUTORIZADO', 'AUTORIZADO'),
        ('NO AUTORIZADO', 'NO AUTORIZADO'),
        ('RECHAZADA', 'RECHAZADA'),
    ], string='Estado SRI', readonly=True, index=True, copy=False, default='NO AUTORIZADO')
    fecha_proceso = fields.Datetime('Fecha procesado', readonly=True, )

    state = fields.Selection([
        ('draft', 'Borrador'),
        ('sent', 'Procesando'),
        ('purchase', 'Orden de Compra'),
        ('invoice', 'Factura de Compra'),
        ('done', 'Hecho'),
        ('cancel', 'Cancelado'),
    ], string='Estado', readonly=True, index=True, copy=False, default='draft', tracking=True)

    estatus_import = fields.Selection([
        ('NONE', 'NO IMPORTADO'),
        ('GET', 'ARCHIVO XML DESCARGADO'),
        ('IMPORT', 'IMPORTADO'),
        ('MAPPING', 'EN HOMOLOGACION'),
        ('ORDER', 'ORDEN DE COMPRA GENERADA'),
        ('INVOICE', 'FACTURA DE COMPRA GENERADA'),
        ('FAIL GET', 'ERROR DE COMUNICACION SRI'),
        ('FAIL READ', 'ERROR DE IMPORTACION XML'),
        ('FAIL PRODUCTS', 'ERROR DE HOMOLOGACION'),
    ], string='Estado Proceso',default='NONE',)

    tipo_importacion= fields.Selection(
        [
            ('sri', 'Desde el SRI'),
            ('file', 'Desde Archivo')
            ],
        'Tipo de importación',default='sri')
    tipo_homologacion = fields.Selection(
        [
            ('auto', 'Homologación automática'),
            ('manual', 'Homologación manual')
            ],
        'Tipo de Homologación', default = 'manual')

    state_purchase_orders = fields.Selection(
        [
            ('draft', 'En borrador'),
            ('done', 'Procesar')
            ], 'Estado de Ordenes de Compras',default=_get_default_state_purchase_orders)

    # ===== EDI fields =====
    l10n_ec_production_env = fields.Boolean(
        string="Use production servers",
        default=True )
    l10n_ec_authorization_date = fields.Char(
        string="Authorization date",
        copy=False, readonly=True )
    fecha_emision = fields.Date(string='Fecha del Documento')
    l10n_latam_document_type_id = fields.Many2one(
        'l10n_latam.document.type', string='Tipo de Documento', auto_join=True, index='btree_not_null')
    l10n_latam_internal_type = fields.Selection(related='l10n_latam_document_type_id.internal_type')
    error = fields.Html(help='The text of the last error that happened during Electronic Invoice operation.')
    blocking_level = fields.Selection(
        selection=[('info', 'Info'), ('warning', 'Warning'), ('error', 'Error')])
    success = fields.Boolean(default=False)
    subtotal_ride = fields.Monetary(string='SubTotal RIDE', readonly=True)
    total_IVA15 = fields.Monetary(string='IVA 15%', readonly=True)
    total_IVA12 = fields.Monetary(string='IVA 12%', readonly=True)
    total_IVA8 = fields.Monetary(string='IVA 8%', readonly=True)
    total_descuento = fields.Monetary(string='Descuento RIDE', readonly=True)
    subtotal_neto = fields.Monetary(string='SubTotal Neto RIDE', readonly=True)
    total = fields.Monetary(string='Total RIDE', readonly=True)
    products_to_map_count = fields.Integer(compute='_products_to_map_count', string='# Productos')
    services_to_map_count = fields.Integer(compute='_products_to_map_count', string='# Servicios')
    lines_no_products_count = fields.Integer(compute='_products_to_map_count', string='# Lineas sin Homologar')
    lines_no_vinculadas_count = fields.Integer(compute='_products_to_map_count', string='# Lineas sin Vincular')
    purchase_ids = fields.One2many('purchase.order', 'edocument_id', string='Ordenes de Compras')
    order_count = fields.Integer(compute='_compute_orders_number', string='Numero de Ordenes')
    ###############################################################################################################
    porcentaje_descuento = fields.Monetary(string='Porcentaje Descuento' ,compute='_calculate_discount')
    total_descuento_lineas = fields.Monetary(string='Descuento Lineas' ,compute='_calculate_discount_lineas')

    @api.depends('order_line.price_unit','order_line.price_discount','order_line.discount')
    def _calculate_discount_lineas(self):
        for order in self:
            discount= sum(order.order_line.mapped('price_discount')) or 0.0
            order.total_descuento_lineas = discount


    @api.depends('total_descuento','total','subtotal_neto','total_descuento_lineas')
    def _calculate_discount(self):
        for order in self:
            if order.total_descuento_lineas==0.0:
                if len(order.order_line)>0:
                    discount = (order.amount_discount / (order.subtotal_ride)) * 100 if order.total_descuento !=0 else 0.0
                else:
                    discount = 0.0
            else:
                if len(order.order_line)>0:
                    discount = (order.total_descuento_lineas / (order.subtotal_ride)) * 100 if order.total_descuento !=0 else 0.0

                else:
                    discount = 0.0
            order.porcentaje_descuento = discount


    @api.depends('purchase_ids')
    def _compute_orders_number(self):
        for edocument in self:
            edocument.order_count = len(edocument.purchase_ids)

    @api.depends('order_line.price_unit', 'total', 'total_descuento')
    def _products_to_map_count(self):
        products_to_map_count = 0
        services_to_map_count = 0
        lines_no_products_count = 0
        lines_no_vinculadas_count = 0
        for mlinea  in self.order_line:
            if mlinea.type=='consu':
                products_to_map_count += 1
            if mlinea.type=='service':
                services_to_map_count += 1
            if not mlinea.product_id:
                lines_no_products_count += 1
            if not mlinea.vinculado:
                lines_no_vinculadas_count += 1
        self.products_to_map_count = products_to_map_count
        self.services_to_map_count = services_to_map_count
        self.lines_no_products_count = lines_no_products_count
        self.lines_no_vinculadas_count = lines_no_vinculadas_count


    def _get_alternative_values(self):
        vals = {
            'edocument_id':self.id,
            'date_order': self.fecha_emision,
            'date_approve': self.fecha_emision,
            'date_planned': self.fecha_emision,
            'partner_id': self.partner_id.id,
            'user_id': self.user_id.id,
            'origin':self.partner_ref,
            'partner_ref':self.partner_ref
        }
        return vals


    ###############################################################################################################


    @api.constrains('company_id', 'order_line')
    def _check_order_line_company_id(self):
        for order in self:
            invalid_companies = order.order_line.product_id.company_id.filtered(
                lambda c: order.company_id not in c._accessible_branches()
            )
            if invalid_companies:
                bad_products = order.order_line.product_id.filtered(
                    lambda p: p.company_id and p.company_id in invalid_companies
                )
                raise ValidationError(_(
                    "Your quotation contains products from company %(product_company)s whereas your quotation belongs to company %(quote_company)s. \n Please change the company of your quotation or remove the products from other companies (%(bad_products)s).",
                    product_company=', '.join(invalid_companies.sudo().mapped('display_name')),
                    quote_company=order.company_id.display_name,
                    bad_products=', '.join(bad_products.mapped('display_name')),
                ))

    def _compute_access_url(self):
        super(ElectronicDocument, self)._compute_access_url()
        for order in self:
            order.access_url = '/my/purchase/%s' % (order.id)

    @api.depends('state', 'date_order', 'date_approve')
    def _compute_date_calendar_start(self):
        for order in self:
            order.date_calendar_start = order.date_approve if (order.state in ['purchase', 'done']) else order.date_order




    @api.depends('name', 'partner_ref', 'amount_total', 'currency_id')
    @api.depends_context('show_total_amount')
    def _compute_display_name(self):
        for po in self:
            name = po.name
            if po.partner_ref:
                name += ' (' + po.partner_ref + ')'
            if self.env.context.get('show_total_amount') and po.amount_total:
                name += ': ' + formatLang(self.env, po.amount_total, currency_obj=po.currency_id)
            po.display_name = name


    @api.depends_context('lang')
    @api.depends('order_line.price_subtotal', 'currency_id', 'company_id')
    def _compute_tax_totals(self):
        AccountTax = self.env['account.tax']
        for order in self:
            if not order.company_id:
                order.tax_totals = False
                continue
            order_lines = order.order_line.filtered(lambda x: not x.display_type)
            base_lines = [line._prepare_base_line_for_taxes_computation() for line in order_lines]
            AccountTax._add_tax_details_in_base_lines(base_lines, order.company_id)
            AccountTax._round_base_lines_tax_details(base_lines, order.company_id)
            order.tax_totals = AccountTax._get_tax_totals_summary(
                base_lines=base_lines,
                currency=order.currency_id or order.company_id.currency_id,
                company=order.company_id,
            )

    @api.depends('company_id.account_fiscal_country_id', 'fiscal_position_id.country_id', 'fiscal_position_id.foreign_vat')
    def _compute_tax_country_id(self):
        for record in self:
            if record.fiscal_position_id.foreign_vat:
                record.tax_country_id = record.fiscal_position_id.country_id
            else:
                record.tax_country_id = record.company_id.account_fiscal_country_id


    def write(self, vals):
        res = super().write(vals)
        return res

    @api.model_create_multi
    def create(self, vals_list):
        orders = self.browse()
        for vals in vals_list:
            company_id = vals.get('company_id', self.default_get(['company_id'])['company_id'])
            self_comp = self.with_company(company_id)
            orders |= super(ElectronicDocument, self_comp).create(vals)
        return orders


    @api.ondelete(at_uninstall=False)
    def _unlink_if_cancelled(self):
        for order in self:
            if not order.state == 'cancel':
                raise UserError(_('Para eliminar una homologacion de compra, primero debes cancelarla.'))

    def copy(self, default=None):
        ctx = dict(self.env.context)
        ctx.pop('default_product_id', None)
        self = self.with_context(ctx)
        new_pos = super().copy(default=default)
        for line in new_pos.order_line:
            if line.product_id:
                seller = line.product_id._select_seller(
                    partner_id=line.partner_id, quantity=line.product_qty,
                    date=line.order_id.date_order and line.order_id.date_order.date(), uom_id=line.product_uom_id)
        return new_pos


    def _get_report_base_filename(self):
        self.ensure_one()
        return 'RIDE-%s' % (self.name)

    @api.onchange('partner_id', 'company_id')
    def onchange_partner_id(self):
        # Ensures all properties and fiscal positions
        # are taken with the company of the order
        # if not defined, with_company doesn't change anything.
        self = self.with_company(self.company_id)
        default_currency = self._context.get("default_currency_id")
        if not self.partner_id:
            self.fiscal_position_id = False
            self.currency_id = default_currency or self.env.company.currency_id.id
        else:
            self.fiscal_position_id = self.env['account.fiscal.position']._get_fiscal_position(self.partner_id)
            self.payment_term_id = self.partner_id.property_supplier_payment_term_id.id
            self.currency_id = default_currency or self.partner_id.property_purchase_currency_id.id or self.env.company.currency_id.id
            if self.partner_id.buyer_id:
                self.user_id = self.partner_id.buyer_id
        return {}

    @api.onchange('fiscal_position_id', 'company_id')
    def _compute_tax_id(self):
        """
        Trigger the recompute of the taxes if the fiscal position is changed on the PO.
        """
        self.order_line._compute_tax_id()

    @api.onchange('partner_id')
    def onchange_partner_id_warning(self):
        if not self.partner_id or not self.env.user.has_group('purchase.group_warning_purchase'):
            return

        partner = self.partner_id

        # If partner has no warning, check its company
        if partner.purchase_warn == 'no-message' and partner.parent_id:
            partner = partner.parent_id

        if partner.purchase_warn and partner.purchase_warn != 'no-message':
            # Block if partner only has warning but parent company is blocked
            if partner.purchase_warn != 'block' and partner.parent_id and partner.parent_id.purchase_warn == 'block':
                partner = partner.parent_id
            title = _("Warning for %s", partner.name)
            message = partner.purchase_warn_msg
            warning = {
                'title': title,
                'message': message
            }
            if partner.purchase_warn == 'block':
                self.update({'partner_id': False})
            return {'warning': warning}
        return {}

    # ------------------------------------------------------------
    # MAIL.THREAD
    # ------------------------------------------------------------

    def message_post(self, **kwargs):
        if self.env.context.get('mark_rfq_as_sent'):
            self.filtered(lambda o: o.state == 'draft').write({'state': 'sent'})
        po_ctx = {'mail_post_autofollow': self.env.context.get('mail_post_autofollow', True)}
        if self.env.context.get('mark_rfq_as_sent') and 'notify_author' not in kwargs:
            kwargs['notify_author'] = self.env.user.partner_id.id in (kwargs.get('partner_ids') or [])
        return super(ElectronicDocument, self.with_context(**po_ctx)).message_post(**kwargs)


    def _track_subtype(self, init_values):
        self.ensure_one()
        if 'state' in init_values and self.state == 'purchase':
            if init_values['state'] == 'invoice':
                return self.env.ref('purchase.mt_rfq_approved')
            return self.env.ref('purchase.mt_rfq_confirmed')
        elif 'state' in init_values and self.state == 'invoice':
            return self.env.ref('purchase.mt_rfq_confirmed')
        elif 'state' in init_values and self.state == 'done':
            return self.env.ref('purchase.mt_rfq_done')
        elif 'state' in init_values and self.state == 'sent':
            return self.env.ref('purchase.mt_rfq_sent')
        return super(ElectronicDocument, self)._track_subtype(init_values)

    # ------------------------------------------------------------
    # ACTIONS
    # ------------------------------------------------------------

    def mapear_lineas_xml(self):
        for mlinea  in self.order_line:
            mlinea.button_crear_producto_desde_linea()


    def button_load(self):
        for edocument in self:
            doc_existe = edocument.exist_same_name(edocument.name)
            if doc_existe:
                msn = "Ya existe un documento importado con los siguientes datos: \nID: %s\nClave de acceso:\nAutorizacion: %s\nEntidad: %s\nFactura: %s\nFecha: %s\nValor: $ %s" % (
                    doc_existe.id,
                    doc_existe.name,
                    doc_existe.partner_id.name,
                    doc_existe.partner_ref,
                    doc_existe.fecha_emision,
                    doc_existe.total
                )
                raise UserError(msn)
            if edocument.state not in ['get','purchase','invoice','cancel']:
                self._l10n_ec_post_move_edi(self)
                self.write({'state': 'sent','fecha_proceso':fields.Datetime.now()})
        return True


    def button_draft(self):
        self.write({'state': 'draft'})
        return {}

    def button_confirm(self):
        for order in self:
            if order.state not in ['draft', 'sent']:
                continue
            order.order_line._validate_analytic_distribution()
            order._add_supplier_to_product()
            order.write({'state': 'invoice'})
            if order.partner_id not in order.message_partner_ids:
                order.message_subscribe([order.partner_id.id])
        return True

    def button_cancel(self):
        purchase_orders_with_invoices = self.filtered(lambda po: any(i.state not in ('cancel', 'draft') for i in po.invoice_ids))
        if purchase_orders_with_invoices:
            raise UserError(_("Unable to cancel purchase order(s): %s. You must first cancel their related vendor bills.", format_list(self.env, purchase_orders_with_invoices.mapped('display_name'))))
        self.write({'state': 'cancel'})

    def button_unlock(self):
        self.write({'state': 'purchase'})

    def button_done(self):
        self.write({'state': 'done', 'priority': '0'})

    def _prepare_supplier_info(self, partner, line, price, currency):
        # Prepare supplierinfo data when adding a product
        return {
            'partner_id': partner.id,
            'sequence': max(line.product_id.seller_ids.mapped('sequence')) + 1 if line.product_id.seller_ids else 1,
            'min_qty': 1.0,
            'price': price,
            'currency_id': currency.id,
            'discount': line.discount,
            'delay': 0,
        }

    def _add_supplier_to_product(self):
        # Add the partner in the supplier list of the product if the supplier is not registered for
        # this product. We limit to 10 the number of suppliers for a product to avoid the mess that
        # could be caused for some generic products ("Miscellaneous").
        for line in self.order_line:
            # Do not add a contact as a supplier
            partner = self.partner_id if not self.partner_id.parent_id else self.partner_id.parent_id
            already_seller = (partner | self.partner_id) & line.product_id.seller_ids.mapped('partner_id')
            if line.product_id and not already_seller and len(line.product_id.seller_ids) <= 10:
                price = line.price_unit
                # Compute the price for the template's UoM, because the supplier's UoM is related to that UoM.
                if line.product_id.product_tmpl_id.uom_id != line.product_uom_id:
                    default_uom = line.product_id.product_tmpl_id.uom_id
                    price = line.product_uom_id._compute_price(price, default_uom)

                supplierinfo = self._prepare_supplier_info(partner, line, price, line.currency_id)
                # In case the order partner is a contact address, a new supplierinfo is created on
                # the parent company. In this case, we keep the product name and code.
                seller = line.product_id._select_seller(
                    partner_id=line.partner_id,
                    quantity=line.product_qty,
                    date=line.order_id.date_order and line.order_id.date_order.date(),
                    uom_id=line.product_uom_id)
                if seller:
                    supplierinfo['product_name'] = seller.product_name
                    supplierinfo['product_code'] = seller.product_code
                    supplierinfo['product_uom_id'] = line.product_uom_id.id
                vals = {
                    'seller_ids': [(0, 0, supplierinfo)],
                }
                # supplier info should be added regardless of the user access rights
                line.product_id.product_tmpl_id.sudo().write(vals)


    def action_create_orden_compra(self):
        # Verifica si ya existe una orden para este documento
        existing_order = self.env['purchase.order'].search([('edocument_id', '=', self.id)], limit=1)
        if existing_order:
            raise UserError("Ya existe una orden de compra asociada a este documento.")

        vals = self._get_alternative_values()
        alt_po = self.env['purchase.order'].with_context(ride=True).create(vals)
        alt_po.onchange_edocument_id()
        alt_po.order_line._compute_tax_id()

        if alt_po:
            self.write({'state': 'purchase','fecha_proceso':fields.Datetime.now()})
            if self.state_purchase_orders=='done':
                alt_po.button_confirm()
            return {
                'type': 'ir.actions.act_window',
                'view_mode': 'form',
                'res_model': 'purchase.order',
                'res_id': alt_po.id,
                'context': {
                    'active_id': alt_po.id,
                },
            }

    def action_view_orden_compra(self):
        # Verifica si existe una orden asociada y muestra solo esa orden
        existing_order = self.env['purchase.order'].search([('edocument_id', '=', self.id)], limit=1)
        if not existing_order:
            raise UserError("No existe ninguna orden de compra asociada a este documento.")

        return {
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_model': 'purchase.order',
            'res_id': existing_order.id,
            'context': {
                'active_id': existing_order.id,
            },
        }

    def action_view_factura_compra(self):
        # Verifica si existe una orden asociada y muestra solo esa orden
        existing_order = self.env['account.move'].search([('edocument_id', '=', self.id)], limit=1)
        if not existing_order:
            raise UserError("No existe ninguna factura de compra asociada a este documento.")

        return {
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_model': 'account.move',
            'res_id': existing_order.id,
            'context': {
                'active_id': existing_order.id,
            },
        }


    def action_create_invoice(self):
        """Create the invoice associated to the PO.
        """
        precision = self.env['decimal.precision'].precision_get('Product Unit')

        # 1) Prepare invoice vals and clean-up the section lines
        invoice_vals_list = []
        sequence = 10
        for order in self:
            if order.invoice_status != 'to invoice':
                continue

            order = order.with_company(order.company_id)
            pending_section = None
            # Invoice values.
            invoice_vals = order._prepare_invoice()
            # Invoice line values (keep only necessary sections).
            for line in order.order_line:
                if line.display_type == 'line_section':
                    pending_section = line
                    continue
                if not float_is_zero(line.qty_to_invoice, precision_digits=precision):
                    if pending_section:
                        line_vals = pending_section._prepare_account_move_line()
                        line_vals.update({'sequence': sequence})
                        invoice_vals['invoice_line_ids'].append((0, 0, line_vals))
                        sequence += 1
                        pending_section = None
                    line_vals = line._prepare_account_move_line()
                    line_vals.update({'sequence': sequence})
                    invoice_vals['invoice_line_ids'].append((0, 0, line_vals))
                    sequence += 1
            invoice_vals_list.append(invoice_vals)

        if not invoice_vals_list:
            raise UserError(_('No existe ninguna línea facturable. Si un producto tiene una política de control basada en la cantidad recibida, asegúrese de que se haya recibido una cantidad.'))

        # 2) group by (company_id, partner_id, currency_id) for batch creation
        new_invoice_vals_list = []
        for _grouping_keys, invoices in groupby(invoice_vals_list, key=lambda x: (x.get('company_id'), x.get('partner_id'), x.get('currency_id'))):
            origins = set()
            payment_refs = set()
            refs = set()
            ref_invoice_vals = None
            for invoice_vals in invoices:
                if not ref_invoice_vals:
                    ref_invoice_vals = invoice_vals
                else:
                    ref_invoice_vals['invoice_line_ids'] += invoice_vals['invoice_line_ids']
                origins.add(invoice_vals['invoice_origin'])
                payment_refs.add(invoice_vals['payment_reference'])
                refs.add(invoice_vals['ref'])
            ref_invoice_vals.update({
                'ref': ', '.join(refs)[:2000],
                'invoice_origin': ', '.join(origins),
                'payment_reference': len(payment_refs) == 1 and payment_refs.pop() or False,
            })
            new_invoice_vals_list.append(ref_invoice_vals)
        invoice_vals_list = new_invoice_vals_list

        # 3) Create invoices.
        moves = self.env['account.move']
        AccountMove = self.env['account.move'].with_context(default_move_type='in_invoice')
        for vals in invoice_vals_list:
            moves |= AccountMove.with_company(vals['company_id']).create(vals)

        # 4) Some moves might actually be refunds: convert them if the total amount is negative
        # We do this after the moves have been created since we need taxes, etc. to know if the total
        # is actually negative or not
        moves.filtered(lambda m: m.currency_id.round(m.amount_total) < 0).action_switch_move_type()
        if moves:
            self.write({'state': 'invoice','fecha_proceso':fields.Datetime.now()})

        return self.action_view_invoice(moves)

    def _prepare_grouped_data(self, rfq):
        return (rfq.partner_id.id, rfq.currency_id.id)

    def _prepare_invoice(self):
        """Prepare the dict of values to create the new invoice for a purchase order.
        """
        self.ensure_one()
        move_type = self._context.get('default_move_type', 'in_invoice')

        partner_invoice = self.env['res.partner'].browse(self.partner_id.address_get(['invoice'])['invoice'])
        partner_bank_id = self.partner_id.commercial_partner_id.bank_ids.filtered_domain(['|', ('company_id', '=', False), ('company_id', '=', self.company_id.id)])[:1]

        invoice_vals = {
            'ref': self.partner_ref or '',
            'move_type': move_type,
            'narration': self.notes,
            'currency_id': self.currency_id.id,
            'partner_id': partner_invoice.id,
            'fiscal_position_id': (self.fiscal_position_id or self.fiscal_position_id._get_fiscal_position(partner_invoice)).id,
            'payment_reference': self.partner_ref or '',
            'partner_bank_id': partner_bank_id.id,
            'invoice_origin': self.name,
            'invoice_payment_term_id': self.payment_term_id.id,
            'invoice_line_ids': [],
            'company_id': self.company_id.id,

        }
        invoice_vals['invoice_date'] = self.fecha_emision
        invoice_vals['l10n_latam_document_number'] = self.partner_ref
        invoice_vals['l10n_ec_authorization_number'] = self.name
        invoice_vals['l10n_ec_sri_payment_id'] =self.env.ref('l10n_ec.P20').id
        invoice_vals['edocument_id'] = self.id

        return invoice_vals

    def action_view_invoice(self, invoices=False):
        """This function returns an action that display existing vendor bills of
        given purchase order ids. When only one found, show the vendor bill
        immediately.
        """
        if not invoices:
            self.invalidate_model(['invoice_ids'])
            invoices = self.invoice_ids

        result = self.env['ir.actions.act_window']._for_xml_id('account.action_move_in_invoice_type')
        # choose the view_mode accordingly
        if len(invoices) > 1:
            result['domain'] = [('id', 'in', invoices.ids)]
        elif len(invoices) == 1:
            res = self.env.ref('account.view_move_form', False)
            form_view = [(res and res.id or False, 'form')]
            if 'views' in result:
                result['views'] = form_view + [(state, view) for state, view in result['views'] if view != 'form']
            else:
                result['views'] = form_view
            result['res_id'] = invoices.id
        else:
            result = {'type': 'ir.actions.act_window_close'}

        return result


    def get_order_timezone(self):
        """ Returns the timezone of the order's user or the company's partner
        or UTC if none of them are set. """
        self.ensure_one()
        return timezone(self.user_id.tz or self.company_id.partner_id.tz or 'UTC')


    def _is_readonly(self):
        """ Return whether the purchase order is read-only or not based on the state.
        A purchase order is considered read-only if its state is 'cancel'.

        :return: Whether the purchase order is read-only or not.
        :rtype: bool
        """
        self.ensure_one()
        return self.state == 'cancel'

    def _get_edi_builders(self):
        return []


    def extract_email_and_info(self, info_adicional):
        print(info_adicional)
        email = None
        other_info = []
        # Palabras clave posibles para identificar el correo electrónico
        email_keywords = ['email', 'mail', 'correo', 'correo electronico']
        for campo in info_adicional:
            if isinstance(campo, dict):  # Asegurarse de que campo sea un diccionario
                field_name = campo.get('@nombre', '').strip().lower()
                field_value = campo.get('#text', '').strip()
                # Verificar si el nombre del campo coincide con alguna palabra clave de email
                if any(keyword in field_name for keyword in email_keywords):
                    email = field_value
                else:
                    # Guardar los campos restantes
                    other_info.append(f"{campo['@nombre']}: {field_value}")
            else:
                print(f"Valor inesperado en info_adicional: {campo}")
        # Devolver el correo y el resto de la información en formato de texto
        return email, "\n".join(other_info)


    def mapear_lineas_xml(self):
        for mlinea  in self.order_line:
            mlinea.button_crear_producto_desde_linea()


    def crear_proveedor(self, info_tributaria, email):

        vals_prov = {}
        table_obj = self.env['res.partner']
        mrecord = table_obj.search([('vat', '=', info_tributaria['ruc'])], limit=1)
        if not mrecord:
            vals_prov['is_company'] = 0
            vals_prov['name'] = str(info_tributaria["razonSocial"]).upper()
            vals_prov['property_account_position_id'] = self.env.ref('account.1_fp_local').id
            # Detectar si es una compañía basada en el nombre
            if ("S.A." in vals_prov['name']) or (" C.A." in vals_prov['name']):
                vals_prov['is_company'] = 1
            vals_prov['vat'] = info_tributaria['ruc']
            vals_prov['country_id'] = 63  # Ecuador
            vals_prov['customer_rank'] = 1
            vals_prov['supplier_rank'] = 1
            vals_prov['lang'] = 'es_EC'
            vals_prov['street'] = info_tributaria["dirMatriz"]
            if email:
                vals_prov['email'] = email
            # Configurar términos de pago
            vals_prov['property_payment_term_id'] = self.env.ref('account.account_payment_term_immediate').id
            vals_prov['property_supplier_payment_term_id'] = self.env.ref('account.account_payment_term_immediate').id
            # Crear el proveedor
            print("-"*60)
            print(vals_prov)
            print("-"*60)
            mrecord = table_obj.create(vals_prov)

        return mrecord
    # ------------------------------------------------------------
    # Interacción con WebServices del SRI
    # ------------------------------------------------------------
    def _prepare_import_line_from_xml(self, line, partner_id):
        product_id = None
        rec =  self.env['edocument.line']
        product_code=line['codigoPrincipal']
        print('partner_id  >>> ',partner_id)
        supplier_code_id= rec.verifica_codes_supplier_prov_xml(product_code, partner_id.id)
        product_code_id= rec.verifica_codes_prod_prov_xml(product_code)
        print('product_code  >>> ',product_code)
        print('supplier_code_id  >>> ',supplier_code_id)
        print('product_code_id  >>> ',product_code_id)
        por_descuento=0.0
        product = None
        template = None
        unificar = False
        distribuir = False
        distribuir_code = ''
        crear = False
        tracking='none'
        type = 'consu'
        product_uom_id = None #self.env.ref('uom.product_uom_unit')
        categ_id = self.env.ref('product.product_category_goods')
        fpos = self.fiscal_position_id or self.fiscal_position_id._get_fiscal_position(partner_id)
        tax_id = self.company_id.l10n_ec_edocument_goods_purchase_tax_id

        if product_code_id:
            product_uom_id=  product_code_id.uom_id
        if supplier_code_id:
            product_id = supplier_code_id.product_id
            unificar  = supplier_code_id.unificar
            distribuir = supplier_code_id.distribuir
            distribuir_code = supplier_code_id.distribuir_code
            product_uom_id=  supplier_code_id.product_uom_id
        if product_code_id:
            product_id = product_code_id
        print('product_id  >>> ',product_id)
        if product_id:
            product = product_id
            template = product_id.product_tmpl_id
            tracking =  product_id.tracking
            type = product_id.type
            product_uom_id=  product_id.uom_id
            categ_id = product_id.categ_id
            tax_id = product_id.supplier_taxes_id._filter_taxes_by_company(self.company_id)
        try:
            por_descuento= (float(line['descuento'])/(float(line['precioUnitario'])*float(line['cantidad'])))*100
        except Exception as e:
            por_descuento = 0.00
        print('product >>> ',product)
        if not product_uom_id:
            product_uom_id=self.env.ref('uom.product_uom_unit')
        print('product_uom_id >>> ',product_uom_id)
        data ={
            'order_id': self.id,
            'name':line['descripcion'],
            'product_name':line['descripcion'],
            'product_code':product_code,
            'product_qty':line['cantidad'],
            'price_unit':line['precioUnitario'],
            'discount':por_descuento,
            'unificar':unificar,
            'distribuir':distribuir,
            'distribuir_code':distribuir_code,
            'crear':crear,
            'tracking':tracking,
            'type':type,
            'product_uom_id':product_uom_id.id,
            'categ_id':categ_id.id,
            'taxes_id': fpos.map_tax(tax_id)
        }
        if product:
            data['vinculado'] = True
            data['product_id']=product.id
            if not supplier_code_id:
                vals_codes={
                'partner_id':partner_id.id,
                'product_name':line['descripcion'],
                'product_code':product_code,
                'product_uom_id':product_uom_id.id,
                'product_id':product.id,
                'product_tmpl_id':product_id.product_tmpl_id.id,
                'unificar':unificar,
                'distribuir':distribuir,
                'distribuir_code':distribuir_code,
                }
                product_supplier_code = self.env['edocument.product.supplier'].create(vals_codes)
        else:
            data['crear'] = True #True Estaba antes, ahora es manual
        return data



    def _l10n_ec_post_move_edi(self, edocuments):
        for edocument in edocuments:
            errors, blocking_level, json_dict = self._l10n_ec_send_xml_to_authorize(edocument)
            print(errors)
            if len(errors)>0:
                raise UserError(errors)

            factura = json_dict.get('factura', {})
            # Extraer la información relevante
            info_tributaria = factura.get('infoTributaria', {})
            infoFactura = factura.get('infoFactura', {})
            detalles = factura.get('detalles', {}).get('detalle', [])
            info_adicional = factura.get('infoAdicional', {}).get('campoAdicional', [])
            # Verificar si 'detalles' es un diccionario en lugar de una lista
            if isinstance(detalles, dict):
                detalles = [detalles]  # Convertir un único detalle en una lista
            # Extraer correo y otros campos adicionales
            email, other_info = self.extract_email_and_info(info_adicional)
            if not email:
                email = 'uno@uno.com'
            # Crear o actualizar el proveedor
            mproveedor = self.crear_proveedor(info_tributaria, email)
            # Manejar la fechaEmision correctamente
            fecha_emision = self.normalize_date_to_odoo(infoFactura.get('fechaEmision'))
            # print('detalles  : ', detalles)
            for mdetail  in edocument.order_line:
                mdetail.unlink()
            lines = []
            for line in detalles:
                mdata=self._prepare_import_line_from_xml(line,mproveedor)
                print(mdata)
                print()
                lines.append((0,0, mdata))
            nro=info_tributaria.get('estab','00') +'-'+ info_tributaria.get('ptoEmi','00') +'-'+ info_tributaria.get('secuencial','000000000')
            totales_impuestos = calcular_total_impuestos_por_tarifa(infoFactura['totalConImpuestos'])
            valor_iva_15 = obtener_valor_iva(totales_impuestos, 'IVA_15')
            valor_iva_12 = obtener_valor_iva(totales_impuestos, 'IVA_12')
            valor_iva_8 = obtener_valor_iva(totales_impuestos, 'IVA_8')
            edocument.write({
                'partner_id': mproveedor.id,
                'partner_ref':nro,
                'success': not errors,
                'fecha_emision':fecha_emision,
                'notes': other_info,
                'error': '<br/>'.join([html_escape(e) for e in errors]),
                'blocking_level': blocking_level,
                'subtotal_ride': (float(infoFactura.get('totalSinImpuestos', 0.0)) + float(infoFactura.get('totalDescuento', 0.0))),
                'subtotal_neto': float(infoFactura.get('totalSinImpuestos', 0.0)),
                'total_IVA15':valor_iva_15,
                'total_IVA12':valor_iva_12,
                'total_IVA8':valor_iva_8,
                'total': float(infoFactura.get('importeTotal', 0.0)),
                'total_descuento': float(infoFactura.get('totalDescuento', 0.0)),
                'order_line':lines,
            })
        return True

    def _l10n_ec_send_xml_to_authorize(self, edocument):
        errors, warnings, auth_states = [], [], []
        json_content = {}
        # Obtener estado de autorización, almacenar la respuesta y manejar errores
        auth_state, auth_num, auth_date, auth_errors, auth_warnings, response_xml = self._l10n_ec_get_authorization_status(edocument)
        errors.extend(auth_errors)
        warnings.extend(auth_warnings)
        auth_states.extend(auth_state or ['NO AUTORIZADO'])
        print('auth_date = ',auth_date)
        if auth_num and auth_date:
            if edocument.name != auth_num:
                warnings.append(_("El número de autorización %(authorization_number)s no coincide con el número del documento %(document_number)s", authorization_number=auth_num, document_number=edocument.name))
            edocument.l10n_ec_authorization_date = auth_date
            edocument.estado_sri = auth_state
            edocument.estatus_import = 'GET'
            # Parsear el XML recibido
            xml_dict = xmltodict.parse(response_xml)
            json_content = json.loads(json.dumps(xml_dict, ensure_ascii=False, indent=2))
        elif not auth_num and auth_state == 'EN PROCESO':
            edocument.estatus_import = 'FAIL GET'
            warnings.append(_("El documento con clave de acceso %s fue recibido por el gobierno y está pendiente de autorización", edocument.name))
        else:
            edocument.estatus_import = 'FAIL GET'
            errors.append(_("El documento no fue autorizado por el SRI. Por favor, intente más tarde"))
        return errors or warnings, 'error' if errors else 'warning', json_content

    def _l10n_ec_get_authorization_status(self, edocument):
        """
        Interacción con el gobierno: recupera el estado de un documento previamente enviado.
        """
        auth_state, auth_num, auth_date = None, None, None
        errors = []
        response_xml = ''

        response, zeep_errors, zeep_warnings = self._l10n_ec_get_client_service_response(
            edocument, "authorization",
            claveAccesoComprobante=edocument.name
        )
        print('response : ',response)
        print('zeep_errors : ',zeep_errors)
        print('zeep_warnings : ',zeep_warnings)

        if zeep_errors or response==None:
            if len(zeep_errors)==0:
                zeep_errors= zeep_warnings
            return auth_state, auth_num, auth_date, zeep_errors, zeep_warnings,response_xml
        try:
            response_auth_list = response.autorizaciones and response.autorizaciones.autorizacion or []
        except AttributeError as err:
            return auth_state, auth_num, auth_date, [_("Respuesta inesperada del SRI: %s", err)], zeep_warnings,response_xml
        if not isinstance(response_auth_list, list):
            response_auth_list = [response_auth_list]

        for doc in response_auth_list:
            auth_state = doc.estado
            if auth_state == "AUTORIZADO":
                auth_num = doc.numeroAutorizacion
                auth_date = doc.fechaAutorizacion
                response_xml = doc.comprobante
            else:
                messages = doc.mensajes
                if messages:
                    messages_list = messages.mensaje
                    if not isinstance(messages_list, list):
                        messages_list = messages
                    for msg in messages_list:
                        errors.append(' - '.join(filter(None, [msg.identificador, msg.informacionAdicional, msg.mensaje, msg.tipo])))

        return auth_state, auth_num, auth_date, errors, zeep_warnings, response_xml


    def _l10n_ec_get_client_service_response(self, edocument, mode, **kwargs):
        """
        Interacción con el gobierno: manejo de transporte SOAP y cliente.
        """
        wsdl_url = PRODUCTION_URL.get(mode) if edocument.l10n_ec_production_env else TEST_URL.get(mode)
        print(wsdl_url)
        errors, warnings = [], []
        response = None
        try:
            # session = requests.Session()
            # session.verify = False  # Deshabilita la verificación SSL
            # transport = Transport(session=session)
            # settings = Settings(strict=False, xml_huge_tree=True)
            # client = Client(wsdl=wsdl_url, settings=settings, transport=transport, timeout=DEFAULT_TIMEOUT_WS)

            client = Client(wsdl=wsdl_url, timeout=DEFAULT_TIMEOUT_WS)
            print(client)
            if mode == "reception":
                response = client.service.validarComprobante(**kwargs)
            elif mode == "authorization":
                response = client.service.autorizacionComprobante(**kwargs)
            if not response:
                errors.append(_("No se recibió respuesta."))
        except ZeepError as e:
            errors.append(_("El servicio del SRI falló con el siguiente error: %s", e))
        except RConnectionError as e:
            warnings.append(_("El servicio del SRI falló con el siguiente mensaje: %s", e))
        return response, errors, warnings


    def normalize_date_to_odoo(self, date):
        if not date:
            return
        res = datetime.strptime(date, '%d/%m/%Y').strftime( '%Y-%m-%d')
        return res


    def normalize_datetime_to_odoo(self, date):
        if not date:
            return
        try:
            try:
                res = datetime.strptime(date[:19], '%d/%m/%Y %H:%M:%S').strftime( '%Y-%m-%d  %H:%M:%S')
            except Exception as e:
                res = datetime.strptime(date[:19], '%Y-%m-%d %H:%M:%S').strftime( '%Y-%m-%d  %H:%M:%S')
        except Exception as ex:
            date = list(date.values())[1]
            res = datetime.strptime(date[:19], '%Y-%m-%dT%H:%M:%S').strftime( '%Y-%m-%d  %H:%M:%S')

        return res

    # ------------------------------------------------------------
    # Métodos de unificación y distribución
    # ------------------------------------------------------------
    def _unify_lines(self, lines, fpos, company, partner, po):
        """
        Unifica líneas agrupándolas por producto y unidad de medida,
        y luego calculando los valores necesarios.
        """
        grouped_lines = defaultdict(list)
        # Agrupar líneas por producto y unidad de medida
        for line in lines:
            grouped_lines[(line.product_id.id, line.product_uom_id.id)].append(line)
        # print(grouped_lines)
        # print()
        unified_lines = []
        for (product_id, uom_id), grouped in grouped_lines.items():
            print(product_id,'   ',uom_id,'    ',grouped)
            product = self.env['product.product'].browse(product_id)
            product_uom_id = self.env['uom.uom'].browse(uom_id)
            total_qty = 0.0
            total_price = 0.0
            total_discount = 0.0
            taxes_set = set()

            # Iterar sobre las líneas agrupadas para acumular cantidades, precios y descuentos
            for line in grouped:
                if line.product_uom_id != product_uom_id:
                    product_qty = line.product_uom_id._compute_quantity(line.product_qty, product_uom_id)
                    price_unit = line.product_uom_id._compute_price(line.price_unit, product_uom_id)
                else:
                    product_qty = line.product_qty
                    price_unit = line.price_unit

                line_total = price_unit * product_qty
                line_discount = line_total * (line.discount / 100.0)

                total_qty += product_qty
                total_price += line_total
                total_discount += line_discount
                # Calcular impuestos
                taxes = fpos.map_tax(product.supplier_taxes_id.filtered(lambda tax: tax.company_id == company)).ids
                taxes_set.update(taxes)

            # Calcular el precio unitario promedio sin el descuento
            price_unit = total_price / total_qty if total_qty else 0.0
            # Usar `_prepare_purchase_order_line` para generar la línea unificada
            line_vals = grouped[0]._prepare_purchase_order_line_from_unify(
                product_id=product,
                price_unit=price_unit,
                product_qty=total_qty,
                product_uom_id=product_uom_id,
                discount=(total_discount / total_price) * 100.0 if total_price else 0.0,
                company_id=company,
                partner=partner,
                po=po
            )
            print(line_vals)
            print()
            unified_lines.append(line_vals)

        return unified_lines


    def _group_and_calculate_distribute(self, lines):
        """
        Agrupa las líneas por distribuir_code y calcula el monto total, la cantidad total y el descuento total para cada grupo.
        """
        res = {}
        for line in lines:
            distribuir_code = line.distribuir_code.strip() if line.distribuir_code else ""
            if not distribuir_code:
                continue

            # Convertir cantidades y precios a la unidad de medida del producto
            if line.product_uom_id != line.product_id.uom_id:
                product_qty = line.product_uom_id._compute_quantity(line.product_qty, line.product_id.uom_id)
                price_unit = line.product_uom_id._compute_price(line.price_unit, line.product_id.uom_id)
            else:
                product_qty = line.product_qty
                price_unit = line.price_unit

            line_total = price_unit * product_qty
            line_discount = line_total * (line.discount / 100.0)

            # Acumular los valores por distribuir_code
            res.setdefault(distribuir_code, {
                'distribuir_code': distribuir_code,
                'total_distribuir': 0.0,
                'total_qty': 0.0,
                'total_descuento': 0.0,
            })
            res[distribuir_code]['total_distribuir'] += line_total
            res[distribuir_code]['total_qty'] += product_qty
            res[distribuir_code]['total_descuento'] += line_discount

        # Convertir el diccionario a una lista ordenada para devolverlo
        grouped_data = sorted(res.values(), key=lambda x: x['distribuir_code'])
        return grouped_data


    def _distribute_lines(self, lines, fpos, company, partner, po):
        """
        Ajusta las líneas distribuidas agrupándolas por distribuir_code y actualiza el price_unit basado en el cálculo.
        """
        # Agrupar y calcular totales por distribuir_code
        grouped_data = self._group_and_calculate_distribute(lines)

        distributed_lines = []
        for data in grouped_data:
            distribuir_code = data['distribuir_code']
            total_qty = data['total_qty']
            total_distribuir = data['total_distribuir']
            total_descuento = data['total_descuento']

            # Calcular el nuevo price_unit para las líneas de este distribuir_code
            if total_qty > 0:
                new_price_unit = total_distribuir / total_qty

            # Filtrar líneas del grupo actual
            group_lines = lines.filtered(lambda line: line.distribuir_code == distribuir_code)
            for line in group_lines:
                if line.product_uom_id != line.product_id.uom_id:
                    product_qty = line.product_uom_id._compute_quantity(line.product_qty, line.product_id.uom_id)
                else:
                    product_qty = line.product_qty

                # Ajustar el price_unit y recalcular descuento si es necesario
                line_vals = line._prepare_purchase_order_line_from_unify(
                    product_id=line.product_id,
                    price_unit=new_price_unit,
                    product_qty=product_qty,
                    product_uom_id=line.product_id.uom_id,
                    discount=(total_descuento / total_distribuir) * 100.0 if total_distribuir > 0 else 0.0,
                    company_id=company,
                    partner=partner,
                    po=po
                )
                distributed_lines.append(line_vals)

        return distributed_lines
