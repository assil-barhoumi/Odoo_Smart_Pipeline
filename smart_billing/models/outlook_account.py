from odoo import models, fields


class SmartBillingOutlookAccount(models.Model):
    _name = 'smart.billing.outlook.account'
    _inherit = ['microsoft.outlook.mixin']
    _description = 'Smart Billing - Outlook Account'

    _OUTLOOK_SCOPE = 'https://outlook.office.com/IMAP.AccessAsUser.All'
    _email_field = 'email'

    name = fields.Char(string='Label', required=True)
    email = fields.Char(string='Email Address', required=True)
