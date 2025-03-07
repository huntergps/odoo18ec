# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
from collections import defaultdict
from datetime import datetime
from dateutil.relativedelta import relativedelta
from pytz import timezone
import xmltodict
import json
from markupsafe import escape, Markup
from werkzeug.urls import url_encode

from odoo import api, Command, fields, models,tools,  _
from odoo.osv import expression
from odoo.tools import format_amount, format_date, format_list, formatLang, groupby,float_compare,float_repr,float_round,html_escape
from odoo.tools.float_utils import float_is_zero
from odoo.exceptions import UserError, ValidationError
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
    _name = "edocument"
    _description = "Documento Electronico"
    _rec_names_search = ['name', 'partner_ref']
    _order = 'priority desc, id desc'


    # @tools.ormcache()
    def _get_default_state_purchase_orders(self):
        company_id = self.company_id.id or self.env.company
        return company_id.l10n_ec_edocument_state_orders

    def exist_same_name(self,name):
        domain=[('name','=',name)]
        hay = self.env['edocument'].search(domain)
        estan = hay-self
        data = (estan and estan[0]) or False
        return data

    @api.depends('document_line.price_subtotal', 'company_id')
    def _amount_all(self):
        AccountTax = self.env['account.tax']
        total_descuento = 0.0
        subtotal = 0.0
        for edocument in self:
            order_lines = edocument.document_line
            base_lines = [line._prepare_base_line_for_taxes_computation() for line in order_lines]
            total_descuento = sum(line.price_discount for line in order_lines)
            subtotal = sum(line.price_init for line in order_lines)
            AccountTax._add_tax_details_in_base_lines(base_lines, edocument.company_id)
            AccountTax._round_base_lines_tax_details(base_lines, edocument.company_id)
            tax_totals = AccountTax._get_tax_totals_summary(
                base_lines=base_lines,
                currency=edocument.currency_id or edocument.company_id.currency_id,
                company=edocument.company_id,
            )
            edocument.amount_untaxed = tax_totals['base_amount_currency']
            edocument.amount_tax = tax_totals['tax_amount_currency']
            edocument.amount_discount = total_descuento
            edocument.amount_subtotal = subtotal
            edocument.amount_total = tax_totals['total_amount_currency']

    name = fields.Char('Autorizacion',size=49, required=True, index='trigram', copy=False, default='')
    priority = fields.Selection(
        [('0', 'Normal'), ('1', 'Urgente')], 'Prioridad', default='0', index=True)
    origin = fields.Char('Source Document', copy=False,
        help="Reference of the document that generated this purchase order "
             "request (e.g. a sales order)")
    partner_ref = fields.Char('Nro Documento', copy=False)
    partner_id = fields.Many2one('res.partner', string='Proveedor', change_default=True, check_company=True)
    currency_id = fields.Many2one('res.currency', 'Moneda', required=True,
        default=lambda self: self.env.company.currency_id.id)
    document_line = fields.One2many('edocument.line', 'document_id', string='Lineas de Documento', copy=True)
    notes = fields.Html('Notas')
    amount_untaxed = fields.Monetary(string='Monto no gravado', store=True, readonly=True, compute='_amount_all')
    tax_totals = fields.Binary(compute='_compute_tax_totals', exportable=False)
    amount_tax = fields.Monetary(string='Impuestos', store=True, readonly=True, compute='_amount_all')
    amount_total = fields.Monetary(string='Total', store=True, readonly=True, compute='_amount_all')
    amount_subtotal = fields.Monetary(string='SubTotal', store=True, readonly=True, compute='_amount_all')
    amount_discount = fields.Monetary(string='Descuento', store=True, readonly=True, compute='_amount_all')
    fiscal_position_id = fields.Many2one('account.fiscal.position', string='Posicion Fiscal', domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]")
    tax_country_id = fields.Many2one(
        comodel_name='res.country',
        compute='_compute_tax_country_id',
        compute_sudo=True)
    tax_calculation_rounding_method = fields.Selection(
        related='company_id.tax_calculation_rounding_method',
        string='Tax calculation rounding method', readonly=True)
    payment_term_id = fields.Many2one('account.payment.term', 'Terminos de Pago', domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]")
    user_id = fields.Many2one(
        'res.users', string='Usuario', index=True,
        default=lambda self: self.env.user, check_company=True)
    company_id = fields.Many2one('res.company', 'Compania', required=True, index=True, default=lambda self: self.env.company.id)
    company_currency_id = fields.Many2one(related="company_id.currency_id", string="Moneda de Compania")
    country_code = fields.Char(related='company_id.account_fiscal_country_id.code', string="Código del país")
    company_price_include = fields.Selection(related='company_id.account_price_include')
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
    ], string='Estado', readonly=True, index=True, copy=False, default='draft')

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
    invoice_count = fields.Integer(compute="_compute_facturas", string='Numero de Facturas', copy=False, default=0, store=True)
    invoice_ids = fields.Many2many('account.move', compute="_compute_facturas", string='Facturas', copy=False, store=True)

    @api.depends('purchase_ids')
    def _compute_orders_number(self):
        for edocument in self:
            edocument.order_count = len(edocument.purchase_ids)

    @api.depends('document_line.invoice_lines.move_id')
    def _compute_facturas(self):
        for order in self:
            invoices = order.mapped('document_line.invoice_lines.move_id')
            order.invoice_ids = invoices
            order.invoice_count = len(invoices)


    @api.depends('document_line.price_unit', 'total', 'total_descuento')
    def _products_to_map_count(self):
        products_to_map_count = 0
        services_to_map_count = 0
        lines_no_products_count = 0
        lines_no_vinculadas_count = 0
        for mlinea  in self.document_line:
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

    def _get_alternative_values(self):
        vals = {
            'edocument_id':self.id,
            'date_order': self.fecha_emision,
            'date_approve': self.fecha_emision,
            'date_planned': self.fecha_emision,
            'partner_id': self.partner_id.id,
            'user_id': self.user_id.id,
            'origin':self.partner_ref,
            # 'origin':self.name + ' (' + self.partner_ref + ')',
            'partner_ref':self.partner_ref
        }
        return vals

    @api.constrains('company_id', 'document_line')
    def _check_document_line_company_id(self):
        for edocument in self:
            invalid_companies = edocument.document_line.product_id.company_id.filtered(
                lambda c: edocument.company_id not in c._accessible_branches()
            )
            if invalid_companies:
                bad_products = edocument.document_line.product_id.filtered(
                    lambda p: p.company_id and p.company_id in invalid_companies
                )
                raise ValidationError(_(
                    "Your quotation contains products from company %(product_company)s whereas your quotation belongs to company %(quote_company)s. \n Please change the company of your quotation or remove the products from other companies (%(bad_products)s).",
                    product_company=', '.join(invalid_companies.sudo().mapped('display_name')),
                    quote_company=edocument.company_id.display_name,
                    bad_products=', '.join(bad_products.mapped('display_name')),
                ))


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
    @api.depends('document_line.price_subtotal', 'currency_id', 'company_id')
    def _compute_tax_totals(self):
        AccountTax = self.env['account.tax']
        for edocument in self:
            if not edocument.company_id:
                edocument.tax_totals = False
                continue
            order_lines = edocument.document_line
            base_lines = [line._prepare_base_line_for_taxes_computation() for line in order_lines]
            AccountTax._add_tax_details_in_base_lines(base_lines, edocument.company_id)
            AccountTax._round_base_lines_tax_details(base_lines, edocument.company_id)
            edocument.tax_totals = AccountTax._get_tax_totals_summary(
                base_lines=base_lines,
                currency=edocument.currency_id or edocument.company_id.currency_id,
                company=edocument.company_id,
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


    @api.onchange('partner_id', 'company_id')
    def onchange_partner_id(self):
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
        self.document_line._compute_tax_id()


    # ------------------------------------------------------------
    # ACTIONS
    # ------------------------------------------------------------
    def button_draft(self):
        self.write({'state': 'draft'})
        return {}

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

    def button_cancel(self):
        self.write({'state': 'cancel'})

    def button_unlock(self):
        self.write({'state': 'purchase'})

    def button_done(self):
        self.write({'state': 'done', 'priority': '0'})


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
        for mlinea  in self.document_line:
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
        por_descuento=0.0
        product = None
        template = None
        unificar = False
        distribuir = False
        distribuir_code = ''
        crear = False
        tracking='none'
        type = 'consu'
        product_uom = None #self.env.ref('uom.product_uom_unit')
        categ_id = self.env.ref('product.product_category_1')
        if product_code_id:
            product_uom=  product_code_id.uom_po_id
        if supplier_code_id:
            product_id = supplier_code_id.product_id
            unificar  = supplier_code_id.unificar
            distribuir = supplier_code_id.distribuir
            distribuir_code = supplier_code_id.distribuir_code
            product_uom=  supplier_code_id.product_uom
        if product_code_id:
            product_id = product_code_id
        if product_id:
            product = product_id
            template = product_id.product_tmpl_id
            tracking =  product_id.tracking
            type = product_id.type
            # product_uom=  product_id.uom_po_id
            categ_id = product_id.categ_id
        try:
            por_descuento= (float(line['descuento'])/(float(line['precioUnitario'])*float(line['cantidad'])))*100
        except Exception as e:
            por_descuento = 0.00
        # print('product = ',product)
        tax_id = self.company_id.l10n_ec_edocument_goods_purchase_tax_id
        fpos = self.fiscal_position_id or self.fiscal_position_id._get_fiscal_position(partner_id)
        data ={
            'document_id': self.id,
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
            'product_uom':product_uom.id,
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
                'product_uom':product_uom.id,
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
            for mdetail  in edocument.document_line:
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
                'document_line':lines,
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

    # Métodos de unificación y distribución
    def _unify_lines(self, lines, fpos, company, partner, po):
        """
        Unifica líneas agrupándolas por producto y unidad de medida,
        y luego calculando los valores necesarios.
        """
        grouped_lines = defaultdict(list)
        # Agrupar líneas por producto y unidad de medida
        for line in lines:
            grouped_lines[(line.product_id.id, line.product_uom.id)].append(line)
        # print(grouped_lines)
        # print()
        unified_lines = []
        for (product_id, uom_id), grouped in grouped_lines.items():
            print(product_id,'   ',uom_id,'    ',grouped)
            product = self.env['product.product'].browse(product_id)
            product_uom = self.env['uom.uom'].browse(uom_id)
            total_qty = 0.0
            total_price = 0.0
            total_discount = 0.0
            taxes_set = set()

            # Iterar sobre las líneas agrupadas para acumular cantidades, precios y descuentos
            for line in grouped:
                if line.product_uom != product_uom:
                    product_qty = line.product_uom._compute_quantity(line.product_qty, product_uom)
                    price_unit = line.product_uom._compute_price(line.price_unit, product_uom)
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
                product_uom=product_uom,
                discount=(total_discount / total_price) * 100.0 if total_price else 0.0,
                company_id=company,
                partner=partner,
                po=po
            )
            print(line_vals)
            print()
            unified_lines.append(line_vals)

        return unified_lines

    def _unify_lines1(self, lines, fpos, company, partner, po):
        """
        Unifica líneas agrupándolas por producto y luego calculando los valores necesarios.
        """
        grouped_lines = defaultdict(list)
        # Agrupar líneas por producto
        for line in lines:
            grouped_lines[line.product_id.id].append(line)
        unified_lines = []
        for product_id, grouped in grouped_lines.items():
            product = self.env['product.product'].browse(product_id)
            total_qty = 0.0
            total_price = 0.0
            total_discount = 0.0
            taxes_set = set()

            # Iterar sobre las líneas agrupadas para acumular cantidades, precios y descuentos
            for line in grouped:
                if line.product_uom != product.uom_po_id:
                    product_qty = line.product_uom._compute_quantity(line.product_qty, product.uom_po_id)
                    price_unit = line.product_uom._compute_price(line.price_unit, product.uom_po_id)
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
                product_uom=product.uom_po_id,
                discount=(total_discount / total_price) * 100.0 if total_price else 0.0,
                company_id=company,
                partner=partner,
                po=po
            )
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
            if line.product_uom != line.product_id.uom_po_id:
                product_qty = line.product_uom._compute_quantity(line.product_qty, line.product_id.uom_po_id)
                price_unit = line.product_uom._compute_price(line.price_unit, line.product_id.uom_po_id)
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
                if line.product_uom != line.product_id.uom_po_id:
                    product_qty = line.product_uom._compute_quantity(line.product_qty, line.product_id.uom_po_id)
                else:
                    product_qty = line.product_qty

                # Ajustar el price_unit y recalcular descuento si es necesario
                line_vals = line._prepare_purchase_order_line_from_unify(
                    product_id=line.product_id,
                    price_unit=new_price_unit,
                    product_qty=product_qty,
                    product_uom=line.product_id.uom_po_id,
                    discount=(total_descuento / total_distribuir) * 100.0 if total_distribuir > 0 else 0.0,
                    company_id=company,
                    partner=partner,
                    po=po
                )
                distributed_lines.append(line_vals)

        return distributed_lines
