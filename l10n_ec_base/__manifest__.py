{
    'name': 'Ecuadorian Localization Base Customization',
    'version': '18.1',
    'summary': 'Base customization module for Ecuadorian localization',
    'description': """
    Este módulo es la personalización base para la localización ecuatoriana.
    """,
    'icon': '/account/static/description/l10n.png',
    'countries': ['ec'],
    'author': 'Elmer Salazar Arias',
    'category': 'Accounting/Localizations/Account Charts',
    'maintainer': 'Elmer Salazar Arias',
    'website': 'http://www.galapagos.tech',
    'email': 'esalazargps@gmail.com',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'base_iban',
        'account_debit_note',
        'l10n_latam_invoice_document',
        'l10n_latam_base',
        'account',
        'l10n_ec',
        'l10n_ec_edi',
        'l10n_ec_reports',
        'l10n_ec_reports_ats',
        'sale',
        'purchase'
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/partner_view.xml',
        'views/stock_picking.xml',
        'views/res_users.xml',
    ],
    'assets': {
        'web._assets_primary_variables': [
            (
                'after',
                'web/static/src/scss/primary_variables.scss',
                'l10n_ec_base/static/src/scss/variables.scss'
            ),
        ],
        'web.assets_backend': [
            'l10n_ec_base/static/src/core/**/*.*',
            'l10n_ec_base/static/src/chatter/*.scss',
            'l10n_ec_base/static/src/chatter/*.xml',
            (
                'after',
                'mail/static/src/chatter/web_portal/chatter.js',
                'l10n_ec_base/static/src/chatter/chatter.js'
            ),
            (
                'after',
                'mail/static/src/chatter/web/form_compiler.js',
                'l10n_ec_base/static/src/views/form/form_compiler.js'
            ),
            'l10n_ec_base/static/src/views/form/form_renderer.js',
        ],
    },
    'demo': [],
    'installable': True,
    'application': True,
    'auto_install': False,
}
