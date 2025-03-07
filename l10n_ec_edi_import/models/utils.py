
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
