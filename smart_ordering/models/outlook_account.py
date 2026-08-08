from odoo import models, fields

from odoo.addons.smart_ordering.utils.crypto_utils import EncryptedChar


class SmartOrderingOutlookAccount(models.Model):
    _name = 'smart.ordering.outlook.account'
    _inherit = ['microsoft.outlook.mixin']
    _description = 'Smart Ordering - Outlook Account'

    _OUTLOOK_SCOPE = 'https://outlook.office.com/IMAP.AccessAsUser.All'
    _email_field = 'email'

    name = fields.Char(string='Label', required=True)
    email = fields.Char(string='Email Address', required=True)
    microsoft_outlook_refresh_token = EncryptedChar(string='Outlook Refresh Token',
        groups='base.group_system', copy=False)
    microsoft_outlook_access_token = EncryptedChar(string='Outlook Access Token',
        groups='base.group_system', copy=False)
