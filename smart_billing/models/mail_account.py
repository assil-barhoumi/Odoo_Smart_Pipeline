from odoo import models, fields


class SmartBillingMailAccount(models.Model):
    _name = 'smart.billing.mail.account'
    _description = 'Smart Billing - Gmail Account'

    name = fields.Char(string='Label', required=True)
    server = fields.Char(string='IMAP Server', required=True, default='imap.gmail.com')
    port = fields.Integer(string='IMAP Port', required=True, default=993)
    email = fields.Char(string='Email Address', required=True)
    password = fields.Char(string='App Password', required=True, groups='base.group_system')
    active = fields.Boolean(default=True)
