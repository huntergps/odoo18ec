# -*- coding: utf-8 -*-
# from odoo import http


# class L10nEcEdiImport(http.Controller):
#     @http.route('/l10n_ec_edi_import/l10n_ec_edi_import', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/l10n_ec_edi_import/l10n_ec_edi_import/objects', auth='public')
#     def list(self, **kw):
#         return http.request.render('l10n_ec_edi_import.listing', {
#             'root': '/l10n_ec_edi_import/l10n_ec_edi_import',
#             'objects': http.request.env['l10n_ec_edi_import.l10n_ec_edi_import'].search([]),
#         })

#     @http.route('/l10n_ec_edi_import/l10n_ec_edi_import/objects/<model("l10n_ec_edi_import.l10n_ec_edi_import"):obj>', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('l10n_ec_edi_import.object', {
#             'object': obj
#         })

