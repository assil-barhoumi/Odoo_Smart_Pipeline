from odoo import models, fields
from odoo.tools import html2plaintext


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
