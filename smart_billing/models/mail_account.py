from odoo import models, fields

from odoo.addons.smart_billing.utils.crypto_utils import decrypt_secret, encrypt_secret


class SmartBillingMailAccount(models.Model):
    _name = 'smart.billing.mail.account'
    _description = 'Smart Billing - Gmail Account'

    name = fields.Char(string='Label', required=True)
    server = fields.Char(string='IMAP Server', required=True, default='imap.gmail.com')
    port = fields.Integer(string='IMAP Port', required=True, default=993)
    email = fields.Char(string='Email Address', required=True)
    password_encrypted = fields.Char(string='App Password (Encrypted)', groups='base.group_system')
    password = fields.Char(
        string='App Password',
        required=True,
        compute='_compute_password',
        inverse='_inverse_password',
        groups='base.group_system',
    )
    active = fields.Boolean(default=True)

    def _compute_password(self):
        for record in self:
            record.password = decrypt_secret(record.password_encrypted)

    def _inverse_password(self):
        for record in self:
            record.password_encrypted = encrypt_secret(record.password)
