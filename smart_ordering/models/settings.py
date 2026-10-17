from odoo import models, fields

from odoo.addons.smart_ordering.utils.crypto_utils import decrypt_secret, encrypt_secret


class SmartOrderingSettings(models.Model):
    _name = 'smart.ordering.settings'
    _description = 'Smart Ordering - Settings'

    qwen_api_key_encrypted = fields.Char(string='Qwen API Key (Encrypted)', groups='base.group_system')
    qwen_api_key = fields.Char(
        string='Qwen API Key',
        compute='_compute_qwen_api_key',
        inverse='_inverse_qwen_api_key',
        groups='base.group_system',
    )

    def _compute_display_name(self):
        for record in self:
            record.display_name = 'AI Configuration'

    def _compute_qwen_api_key(self):
        for record in self:
            record.qwen_api_key = decrypt_secret(record.qwen_api_key_encrypted)

    def _inverse_qwen_api_key(self):
        for record in self:
            record.qwen_api_key_encrypted = encrypt_secret(record.qwen_api_key)
