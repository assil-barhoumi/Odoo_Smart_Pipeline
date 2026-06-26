import json
from odoo import models, fields
from odoo.tools import html2plaintext
from odoo.addons.smart_ordering.utils.llm_utils import extract_order


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
    email_body = fields.Text(string='Order Content', readonly=True)
    received_at = fields.Datetime(string='Received At', readonly=True)
    status = fields.Selection([
        ('pending', 'Pending'),
        ('extracted', 'Extracted'),
        ('pushed', 'Pushed'),
        ('skipped', 'Skipped'),
        ('failed', 'Failed'),
    ], string='Status', default='pending', required=True, tracking=True)
    extracted_json = fields.Text(string='Extracted Data', readonly=True)
    confidence = fields.Float(string='Confidence', readonly=True)
    error_message = fields.Text(string='Error', readonly=True)
    sale_order_id = fields.Many2one(
        'sale.order',
        string='Sale Order',
        readonly=True,
        ondelete='set null',
    )

    def message_new(self, msg_dict, custom_values=None):
        if custom_values is None:
            custom_values = {}
        custom_values.update({
            'sender_email': msg_dict.get('email_from', ''),
            'email_body': html2plaintext(msg_dict.get('body', '')).strip(),
            'received_at': msg_dict.get('date'),
        })
        return super().message_new(msg_dict, custom_values)

    def _run_pipeline(self):
        server = self.env['fetchmail.server'].search([
            ('object_id.model', '=', 'smart.order')
        ], limit=1)
        if server:
            server.fetch_mail()
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
                partner = self.env['res.partner'].sudo().search(
                    [('email', '=', record.sender_email)], limit=1
                )
                if not partner:
                    partner = self.env['res.partner'].sudo().create({
                        'name': extracted.get('client_name') or record.sender_email,
                        'email': record.sender_email,
                        'customer_rank': 1,
                    })
                order = self.env['sale.order'].sudo().create({
                    'partner_id': partner.id,
                    'origin': f'Smart Order #{record.id}',
                    'user_id': record.create_uid.id,
                })
                for item in extracted.get('line_items', []):
                    self.env['sale.order.line'].sudo().create({
                        'order_id': order.id,
                        'name': item.get('description', ''),
                        'product_uom_qty': item.get('quantity') or 0,
                        'price_unit': 0,
                    })
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
        api_key = self.env['ir.config_parameter'].sudo().get_param('smart_ordering.groq_api_key')
        for record in self:
            try:
                result = extract_order(record.email_body, api_key)
                record.sudo().write({
                    'extracted_json': json.dumps(result),
                    'confidence': result.get('confidence', 0.0),
                    'status': 'extracted',
                    'error_message': False,
                })
            except Exception as e:
                record.sudo().write({
                    'status': 'failed',
                    'error_message': str(e),
                })
