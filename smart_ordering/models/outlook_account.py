from odoo import models, fields


class SmartOrderingOutlookAccount(models.Model):
    _name = 'smart.ordering.outlook.account'
    _inherit = ['microsoft.outlook.mixin']
    _description = 'Smart Ordering - Outlook Account'

    _OUTLOOK_SCOPE = 'https://outlook.office.com/IMAP.AccessAsUser.All'
    _email_field = 'email'

    name = fields.Char(string='Label', required=True)
    email = fields.Char(string='Email Address', required=True)
