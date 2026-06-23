from odoo import models, fields


class SmartOrder(models.Model):
    _name = 'smart.order'
    _inherit = ['mail.thread']
    _description = 'Smart Order'
    _rec_name = 'name'

    unique_sale_order = models.Constraint(
        'UNIQUE(sale_order_id)',
        'A sale order can only be linked to one smart order.',
    )

    name = fields.Char(string='Subject', required=True)
    sender_email = fields.Char(string='Sender', readonly=True)
    email_body = fields.Text(string='Order Content', readonly=True)
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
