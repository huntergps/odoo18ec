{
    'name': 'Ecuadorian Payment Customization',
    'version': '18.11',
    'summary': 'Customization module for Ecuadorian localization Payments',
    'description': """
    Este módulo es la personalización de pagos para la localización ecuatoriana.
    """,
    'icon': '/account/static/description/l10n.png',
    'countries': ['ec'],
    'author': 'Elmer Salazar Arias',
    'category': 'Accounting/Localizations/Payments',
    'maintainer': 'Elmer Salazar Arias',
    'email': 'esalazargps@gmail.com',
    'website': 'http://www.galapagos.tech',
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
        'data/account_payment_method_data.xml',
        'data/account_credit_card_brand_data.xml',
        'data/account_credit_card_deadline_data.xml',
        'data/ir_sequence.xml',
        'security/account_security.xml',
        'security/ir.model.access.csv',
        'views/account_payment_view.xml',
        'views/account_journal_view.xml',
        'views/account_advance_view.xml',
        'views/account_move_view.xml',
        'views/account_menuitem.xml',
        'views/account_credit_card_brand_view.xml',
        'views/account_credit_card_deadline_view.xml',
        'views/res_config_settings_views.xml'

    ],
    'installable': True,
    'post_init_hook': '_initialize_journals',
}
