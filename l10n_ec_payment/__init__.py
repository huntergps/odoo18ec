from . import models

from odoo import api, SUPERUSER_ID

def _initialize_journals(env):
    company = env.user.company_id


    journals_data1 = [
        {'name': 'Bco Pichincha cta cte 2100136006', 'type': 'bank', 'code': 'BPICH'},
        {'name': 'Valoración del inventario', 'type': 'general', 'code': 'INVEN'},
        {'name': 'Anticipos de Clientes', 'type': 'general', 'code': 'ADV_O'},
        {'name': 'Anticipos a Proveedores', 'type': 'general', 'code': 'ADV_I'},
        {'name': 'Ventas TC DATAFAST', 'type': 'credit', 'code': 'DTAF'},
        {'name': 'Ventas TC MEDIANET', 'type': 'credit', 'code': 'MEDN'},
        {'name': 'Ventas TC DATA EXPRESS', 'type': 'credit', 'code': 'DAEX'},
        {'name': 'Caja 01', 'type': 'cash', 'code': 'CAJ1'},
        {'name': 'Caja 02', 'type': 'cash', 'code': 'CAJ2'},
        {'name': 'Produbanco cta aho 06178946003', 'type': 'bank', 'code': 'BPROD'},
        {'name': 'Bco Guayaquil cta aho 35601648', 'type': 'bank', 'code': 'BGYA'},
        {'name': 'Bco Pacifico cta cte 7544308', 'type': 'bank', 'code': 'BPACC'},
        {'name': 'PayPal', 'type': 'bank', 'code': 'PAYP'},
        {'name': 'PayPhone', 'type': 'bank', 'code': 'PPHON'},
        {'name': 'Bco Pichincha cta aho 4665360000', 'type': 'bank', 'code': 'BPICH'},
        {'name': 'Bco Solidario 5927002724817', 'type': 'bank', 'code': 'BNK1'},
        {'name': 'Diario Nómina', 'type': 'general', 'code': 'RRHH'},
        {'name': 'Saldos iniciales', 'type': 'general', 'code': 'SALDS'},
        {'name': 'Dscto en ROL', 'type': 'general', 'code': 'DCROL'},
        {'name': 'Otros Cruces de ctas', 'type': 'general', 'code': 'CTAEA'},
        {'name': 'Caja Chica Administración', 'type': 'cash', 'code': 'CCHIA'},
        {'name': 'Fondo por rendir', 'type': 'cash', 'code': 'FR'},
        {'name': 'Tarjeta ERIK DINERS', 'type': 'credit', 'code': 'TCDIN'},
        {'name': 'Tarjeta ERIK PACIFICARD', 'type': 'credit', 'code': 'TCPAC'},
        {'name': 'Tarjeta Corporativa VISA', 'type': 'credit', 'code': 'TCCOR'},
        {'name': 'Tarjeta ERIK AMEX', 'type': 'credit', 'code': 'AMEX'},
        {'name': 'Tarjeta Corporativa DINERS', 'type': 'credit', 'code': 'DINER'},
        {'name': 'Cruce ctas clientes', 'type': 'general', 'code': 'CRUCS'},
        {'name': 'TC recaps', 'type': 'general', 'code': 'CRUCS'},
        {'name': 'PayBill', 'type': 'general', 'code': 'Pbill'},
        {'name': 'TC Andrés Cusme', 'type': 'general', 'code': 'ACUSM'},
        {'name': 'TC Sara Portugal', 'type': 'general', 'code': 'TCSP'},
        {'name': 'Efectivo sueltos caja', 'type': 'cash', 'code': 'EFES'},
        {'name': 'Bco. Bolivariano Ahorro 1751090986', 'type': 'bank', 'code': 'BNK2'},
        {'name': 'Cripto-BITCOIN-BTC', 'type': 'bank', 'code': 'BTC'},
        {'name': 'Cripto-TETHER-USDT', 'type': 'bank', 'code': 'USDST'},
        {'name': 'Cripto-ESTABLE COIN-BUSD y USDT', 'type': 'bank', 'code': 'ESTAB'},
        {'name': 'Ventas Web PAYMENTEZ', 'type': 'general', 'code': 'BPPMZ'},
        {'name': 'Ventas Web PLACETOPAY', 'type': 'general', 'code': 'BPPTP'},
        {'name': 'Por pagar Erik Aldás', 'type': 'general', 'code': 'XPEA'},
        {'name': 'Bco Diners ahorro 1000121629', 'type': 'bank', 'code': 'BNK3'},
        {'name': 'Intereses financieros préstamo', 'type': 'general', 'code': 'INTF'},
        {'name': 'MercadoPago', 'type': 'general', 'code': 'MKPG'},
        {'name': 'Rappi', 'type': 'general', 'code': 'RAPPI'},
        {'name': 'Bco Pichincha cta aho 2210320445', 'type': 'bank', 'code': 'PICH3'},
        {'name': 'Gift Card Tecnosmart', 'type': 'credit', 'code': 'GIFTC'},
        {'name': 'Baja cartera antigua incobrable', 'type': 'general', 'code': 'BCIN'},
    ]

    # for journal_data in journals_data:
    #     if not env['account.journal'].search([('code', '=', journal_data['code']), ('company_id', '=', company.id)]):
    #         env['account.journal'].create({
    #             'name': journal_data['name'],
    #             'type': journal_data['type'],
    #             'code': journal_data['code'],
    #             'company_id': company.id,
    #         })
