# -*- coding: utf-8 -*-
{
    'name': 'Ecuadorian Electronics Documents Import',
    'version': '18.1',
    'summary': 'Ecuadorian localization to import Electronics Documents',
    'description': """
    Este módulo permite la importacin de XML de documentos electronicos para la localización ecuatoriana.
    """,
    'icon': '/account/static/description/l10n.png',
    'countries': ['ec'],
    'author': 'Elmer Salazar Arias',
    "category": "Accounting/Localizations/EDI",
    'maintainer': 'Elmer Salazar Arias',
    'website': 'http://www.galapagos.tech',

    'license': 'LGPL-3',
    'depends': [
        "account_edi",
        'l10n_ec',
        'stock',
        'l10n_ec_base'
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'views/product_supplierinfo_views.xml',
        'views/product_views.xml',
        'views/purchase_views.xml',
        'views/edocument_views.xml',
    ],
    'demo': [],
    'installable': True,
    'application': True,
    'auto_install': False,
    'maintainer': 'Elmer Salazar Arias',
    'email': 'esalazargps@gmail.com',
}
