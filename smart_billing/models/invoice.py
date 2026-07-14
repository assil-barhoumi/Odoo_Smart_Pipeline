import base64
import json
import logging

from odoo import api, models, fields
from odoo.addons.smart_billing.utils.gmail_utils import acquire_emails
from odoo.addons.smart_billing.utils.outlook_utils import acquire_emails_outlook
from odoo.addons.smart_billing.utils.llm_utils import extract_invoice

_logger = logging.getLogger(__name__)


class SmartInvoiceLine(models.Model):
    _name = 'smart.invoice.line'
    _description = 'Smart Invoice Line'

    invoice_id = fields.Many2one('smart.invoice', ondelete='cascade', required=True)
    description = fields.Char()
    quantity = fields.Float(digits=(16, 4))
    unit_price = fields.Float(digits=(16, 4))
    total_line = fields.Float(digits=(16, 4))
    item_type = fields.Char()


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
    invoice_file = fields.Binary(string='Invoice Preview', readonly=True, attachment=True)
    is_pdf = fields.Boolean(string='Is PDF', compute='_compute_is_pdf', store=True)

    supplier_name = fields.Char(string='Supplier')
    supplier_street = fields.Char(string='Supplier Address')
    supplier_country = fields.Char(string='Supplier Country')
    invoice_number = fields.Char(string='Invoice Number')
    invoice_date = fields.Date(string='Invoice Date')
    total_ht = fields.Float(string='Total HT', digits=(16, 3))
    vat_amount = fields.Float(string='VAT Amount', digits=(16, 3))
    total_ttc = fields.Float(string='Total TTC', digits=(16, 3))
    currency_code = fields.Char(string='Currency')
    line_ids = fields.One2many('smart.invoice.line', 'invoice_id', string='Line Items')

    confidence = fields.Float(string='Confidence', readonly=True)
    extracted_error = fields.Char(string='Extraction Error', readonly=True)
    extracted_json = fields.Text(string='Extracted Data', readonly=True)

    status = fields.Selection([
        ('pending', 'Pending'),
        ('extracted', 'Extracted'),
        ('validated', 'Validated'),
        ('rejected', 'Rejected'),
    ], string='Status', default='pending', required=True, tracking=True, index=True)
    move_id = fields.Many2one(
        'account.move',
        string='Vendor Bill',
        readonly=True,
        ondelete='set null',
    )

    @api.depends('file_name')
    def _compute_is_pdf(self):
        for rec in self:
            rec.is_pdf = bool(rec.file_name) and rec.file_name.lower().endswith('.pdf')

    def _acquire_emails(self):
        try:
            acquire_emails(self.env)
        except Exception as e:
            _logger.error('smart_billing: Gmail acquisition failed: %s', e)
        try:
            acquire_emails_outlook(self.env)
        except Exception as e:
            _logger.error('smart_billing: Outlook acquisition failed: %s', e)

    def _run_extraction(self):
        api_key = self.env['ir.config_parameter'].sudo().get_param('smart_billing.groq_api_key')
        if not api_key:
            _logger.error('smart_billing: groq_api_key not configured')
            return

        pending = self.sudo().search([('status', '=', 'pending')])
        for invoice in pending:
            try:
                attachment = self.env['ir.attachment'].sudo().search([
                    ('res_model', '=', 'smart.invoice'),
                    ('res_id', '=', invoice.id),
                ], limit=1)
                if not attachment:
                    continue

                data = base64.b64decode(attachment.datas)
                result = extract_invoice(data, attachment.name, api_key)

                line_items = result.get('line_items') or []
                line_cmds = [(0, 0, {
                    'description': item.get('description') or '',
                    'quantity': float(item.get('quantity') or 1.0),
                    'unit_price': float(item.get('unit_price') or 0.0),
                    'total_line': float(item.get('total_line') or 0.0),
                    'item_type': item.get('item_type') or '',
                }) for item in line_items]

                invoice.sudo().write({
                    'invoice_file': attachment.datas,
                    'supplier_name': result.get('supplier_name'),
                    'supplier_street': result.get('supplier_street'),
                    'supplier_country': result.get('supplier_country'),
                    'invoice_number': result.get('invoice_number'),
                    'invoice_date': result.get('date'),
                    'total_ht': result.get('total_ht'),
                    'vat_amount': result.get('vat_amount'),
                    'total_ttc': result.get('total_ttc'),
                    'currency_code': result.get('currency'),
                    'confidence': result.get('confidence', 0.0),
                    'extracted_error': False,
                    'extracted_json': json.dumps(result, ensure_ascii=False),
                    'status': 'extracted',
                    'line_ids': line_cmds,
                })
                _logger.info('smart_billing: extracted %s confidence=%.2f', invoice.file_name, result.get('confidence', 0.0))
            except Exception as e:
                _logger.error('smart_billing: extraction failed for %s: %s', invoice.file_name, e)
                invoice.sudo().write({'extracted_error': str(e)})

