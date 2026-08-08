from odoo import models, fields

from odoo.addons.smart_billing.utils.crypto_utils import decrypt_secret, encrypt_secret


class SmartBillingSettings(models.Model):
    _name = 'smart.billing.settings'
    _description = 'Smart Billing - Settings'

    mistral_api_key_encrypted = fields.Char(string='Mistral API Key (Encrypted)', groups='base.group_system')
    mistral_api_key = fields.Char(
        string='Mistral API Key',
        compute='_compute_mistral_api_key',
        inverse='_inverse_mistral_api_key',
        groups='base.group_system',
    )

    def _compute_mistral_api_key(self):
        for record in self:
            record.mistral_api_key = decrypt_secret(record.mistral_api_key_encrypted)

    def _inverse_mistral_api_key(self):
        for record in self:
            record.mistral_api_key_encrypted = encrypt_secret(record.mistral_api_key)
