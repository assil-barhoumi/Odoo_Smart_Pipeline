import logging

from odoo import models, fields
from odoo.addons.smart_billing.utils.gmail_utils import acquire_emails
from odoo.addons.smart_billing.utils.outlook_utils import acquire_emails_outlook

_logger = logging.getLogger(__name__)

class SmartInvoice(models.Model):
    _name = 'smart.invoice'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Smart Invoice'
    _rec_name = 'file_name'
    _order = 'received_at desc'

    sender_email = fields.Char(string='Sender', readonly=True)
    received_at = fields.Datetime(string='Received At', readonly=True)
    source = fields.Selection([
        ('gmail', 'Gmail'),
        ('outlook', 'Outlook'),
    ], string='Source', readonly=True)
    message_id = fields.Char(string='Message-ID', readonly=True, index=True)
    file_name = fields.Char(string='Attachment', required=True, readonly=True)
    file_hash = fields.Char(string='File Hash', readonly=True, index=True)

    supplier_name = fields.Char(string='Supplier')
    supplier_street = fields.Char(string='Supplier Address')
    supplier_country = fields.Char(string='Supplier Country')
    invoice_number = fields.Char(string='Invoice Number')
    invoice_date = fields.Date(string='Invoice Date')
    total_ht = fields.Float(string='Total HT', digits=(16, 3))
    vat_amount = fields.Float(string='VAT Amount', digits=(16, 3))
    total_ttc = fields.Float(string='Total TTC', digits=(16, 3))
    currency_code = fields.Char(string='Currency')

    confidence = fields.Float(string='Confidence', readonly=True)
    extracted_json = fields.Text(string='Extracted Data', readonly=True)

    status = fields.Selection([
        ('pending', 'Pending Review'),
        ('pushed', 'Pushed'),
        ('rejected', 'Rejected'),
    ], string='Status', default='pending', required=True, tracking=True, index=True)
    move_id = fields.Many2one(
        'account.move',
        string='Vendor Bill',
        readonly=True,
        ondelete='set null',
    )

    def _acquire_emails(self):
        try:
            acquire_emails(self.env)
        except Exception as e:
            _logger.error('smart_billing: Gmail acquisition failed: %s', e)
        try:
            acquire_emails_outlook(self.env)
        except Exception as e:
            _logger.error('smart_billing: Outlook acquisition failed: %s', e)

