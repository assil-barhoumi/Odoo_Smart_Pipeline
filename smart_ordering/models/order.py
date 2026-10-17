import base64
import hashlib
import html
import json
import logging

from odoo import api, models, fields
from odoo.addons.smart_ordering.utils.llm_utils import extract_order, AuthenticationError
from odoo.addons.smart_ordering.utils.gmail_utils import acquire_emails
from odoo.addons.smart_ordering.utils.outlook_utils import acquire_emails_outlook
from odoo.addons.smart_ordering.utils.attachment_utils import extract_text_from_attachment


_logger = logging.getLogger(__name__)

EXTRACTION_MAX_ATTEMPTS = 2


class SmartOrder(models.Model):
    _name = 'smart.order'
    _inherit = ['mail.thread']
    _description = 'Smart Order'
    _rec_name = 'name'

    _unique_sale_order = models.Constraint(
        'UNIQUE(sale_order_id)',
        'A sale order can only be linked to one smart order.',
    )

    name = fields.Char(string='Subject', required=True)
    sender_email = fields.Char(string='Sender', readonly=True)
    recipient_email = fields.Char(string='Recipient', readonly=True, help='Mailbox address that received this order, used as the From address for the confirmation reply.')
    email_body = fields.Text(string='Order Content', readonly=True)
    received_at = fields.Datetime(string='Received At', readonly=True)
    source = fields.Selection([
        ('gmail', 'Gmail'),
        ('outlook', 'Outlook'),
    ], string='Source', readonly=True)
    message_id = fields.Char(string='Message-ID', readonly=True, index=True)
    # Display-only, collision-tolerant hash of message_id. Never use for identity/dedup checks — use message_id instead.
    message_id_short = fields.Char(
        string='Email Ref', compute='_compute_message_id_short', store=True,
        help='Short reference derived from Message-ID, for display only — not a unique identifier.',
    )
    status = fields.Selection([
        ('pending', 'Pending'),
        ('extracted', 'Extracted'),
        ('pushed', 'Pushed'),
        ('skipped', 'Skipped'),
        ('failed', 'Failed'),
    ], string='Status', default='pending', required=True, tracking=True)
    extracted_json = fields.Text(string='Extracted Data', readonly=True)
    suspected_multi_order = fields.Boolean(
        string='Suspected Multiple Orders', readonly=True,
        help='LLM suspects this email bundles multiple separate orders rather than one order split across attachments. Does not block auto-push — surfaced as a review activity on the resulting quotation instead.',
    )
    confidence = fields.Float(string='Confidence', readonly=True)
    # Display-only: Odoo's progressbar widget treats max_value as a field lookup, never a literal
    # number, so a plain 0-100 field is needed to make the bar render correctly against a 0.0-1.0 confidence.
    confidence_pct = fields.Integer(string='Confidence %', compute='_compute_confidence_pct')
    error_message = fields.Text(string='Error', readonly=True)
    sale_order_id = fields.Many2one(
        'sale.order',
        string='Sale Order',
        readonly=True,
        ondelete='set null',
    )

    @api.depends('message_id')
    def _compute_message_id_short(self):
        for record in self:
            record.message_id_short = (
                hashlib.md5(record.message_id.encode()).hexdigest()[:8]
                if record.message_id else False
            )

    @api.depends('confidence')
    def _compute_confidence_pct(self):
        for record in self:
            record.confidence_pct = round((record.confidence or 0.0) * 100)

    def action_run_extraction(self):
        self.check_access_rights('write')
        self._run_extraction()

    def action_push_to_erp(self):
        self.check_access_rights('write')
        self._push_to_erp()

    def action_reset_to_pending(self):
        self.write({'status': 'pending', 'error_message': False})

    def _acquire_emails(self):
        try:
            acquire_emails(self.env)
        except Exception as e:
            _logger.error('smart_ordering: Gmail acquisition failed: %s', e)
        try:
            acquire_emails_outlook(self.env)
        except Exception as e:
            _logger.error('smart_ordering: Outlook acquisition failed: %s', e)

    def _run_pipeline(self):
        try:
            self._acquire_emails()
        except Exception as e:
            _logger.error('smart_ordering: acquisition failed: %s', e)
        self.env.invalidate_all()
        self.search([('status', '=', 'pending')])._run_extraction()
        self.search([('status', '=', 'extracted')])._push_to_erp()

    def _push_to_erp(self):
        for record in self:
            try:
                extracted = json.loads(record.extracted_json)
                if not extracted.get('line_items'):
                    record.sudo().write({
                        'status': 'skipped',
                        'error_message': 'No items extracted',
                    })
                    continue
                # Everything below has side effects (partner/order/line creation) and isn't
                # safe to half-apply, so one savepoint covers the whole attempt: if any part
                # fails, nothing here is left behind for a retry to duplicate.
                with self.env.cr.savepoint():
                    partner = self.env['res.partner'].sudo().search(
                        [('email', '=', record.sender_email)], limit=1
                    )
                    client_name = extracted.get('client_name')
                    partner_name_mismatch = False
                    if not partner:
                        partner = self.env['res.partner'].sudo().create({
                            'name': client_name or record.sender_email,
                            'email': record.sender_email,
                            'customer_rank': 1,
                        })
                    elif client_name and client_name.strip().casefold() != (partner.name or '').strip().casefold():
                        partner_name_mismatch = True
                    order = self.env['sale.order'].with_context(tracking_disable=True).sudo().create({
                        'partner_id': partner.id,
                        'origin': f'Smart Order #{record.id}',
                        'user_id': self.env.ref('base.user_admin').id,
                        'note': f'<p>{html.escape(extracted["notes"])}</p>' if extracted.get('notes') else False,
                    })
                    source_attachments = self.env['ir.attachment'].sudo().search([
                        ('res_model', '=', 'smart.order'),
                        ('res_id', '=', record.id),
                    ])
                    source_attachments.copy({'res_model': 'sale.order', 'res_id': order.id})
                    groups = {}
                    for item in extracted.get('line_items', []):
                        groups.setdefault(item.get('source') or 'Other', []).append(item)
                    for source, items in groups.items():
                        self.env['sale.order.line'].sudo().create({
                            'order_id': order.id,
                            'display_type': 'line_section',
                            'name': source,
                        })
                        for item in items:
                            self.env['sale.order.line'].sudo().create({
                                'order_id': order.id,
                                'name': item.get('description', ''),
                                'product_uom_qty': item.get('quantity') or 0,
                                'price_unit': 0,
                            })
                    if extracted.get('suspected_multi_order'):
                        order.sudo().activity_schedule(
                            'mail.mail_activity_data_todo',
                            user_id=self.env.ref('base.user_admin').id,
                            summary='Suspected multiple orders bundled in one email',
                            note=(
                                'The extraction AI suspects this email\'s attachments describe '
                                'multiple separate orders rather than one order split across supporting '
                                'files. Please review the line items below before confirming this quotation.'
                            ),
                        )
                    if partner_name_mismatch:
                        order.sudo().activity_schedule(
                            'mail.mail_activity_data_todo',
                            user_id=self.env.ref('base.user_admin').id,
                            summary='Customer name may be outdated',
                            note=(
                                f'This order\'s email signature suggests the customer name is '
                                f'"{html.escape(client_name)}", but the matched contact ({partner.name}) '
                                f'is named differently. Please review and update the contact if needed.'
                            ),
                        )
                    record.sudo().write({
                        'sale_order_id': order.id,
                        'status': 'pushed',
                        'error_message': False,
                    })
            except Exception as e:
                record.sudo().write({
                    'status': 'failed',
                    'error_message': str(e),
                })

    def _run_extraction(self):
        settings = self.env['smart.ordering.settings'].sudo().search([], limit=1)
        api_key = settings.qwen_api_key if settings else False
        for record in self:
            attachments = self.env['ir.attachment'].sudo().search([
                ('res_model', '=', 'smart.order'),
                ('res_id', '=', record.id),
            ])
            parts = []
            if record.email_body:
                parts.append(f"EMAIL BODY:\n{record.email_body}")
            for att in attachments:
                text = extract_text_from_attachment(att.name, base64.b64decode(att.datas))
                if text:
                    parts.append(f"ATTACHMENT ({att.name}):\n{text}")
                    _logger.info('smart_ordering: including attachment %r for record %d', att.name, record.id)
            content = '\n\n---\n\n'.join(parts)

            error = None
            stop_batch = False
            for attempt in range(EXTRACTION_MAX_ATTEMPTS):
                try:
                    result = extract_order(content, api_key)
                    record.sudo().write({
                        'extracted_json': json.dumps(result),
                        'confidence': result.get('confidence', 0.0),
                        'suspected_multi_order': result.get('suspected_multi_order', False),
                        'status': 'extracted',
                        'error_message': False,
                    })
                    error = None
                    break
                except AuthenticationError as e:
                    # The key is wrong, not this document — retrying it, or any other
                    # record in this batch, won't help until it's fixed in settings.
                    error = e
                    stop_batch = True
                    break
                except Exception as e:
                    error = e
                    _logger.warning('smart_ordering: extraction attempt %d/%d failed for record %d: %s',
                                     attempt + 1, EXTRACTION_MAX_ATTEMPTS, record.id, e)
            if error:
                record.sudo().write({'status': 'failed', 'error_message': str(error)})
            if stop_batch:
                _logger.error('smart_ordering: stopping extraction batch, invalid API key: %s', error)
                break
