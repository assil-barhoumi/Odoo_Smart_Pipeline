import imaplib

from odoo.addons.smart_ordering.utils.imap_shared import ORDER_KEYWORDS, create_order_record, process_emails


def acquire_emails_outlook(env):
    server = env['fetchmail.server'].sudo().search([
        ('server_type', '=', 'outlook'),
        ('active', '=', True),
    ], limit=1)
    if not server:
        return
    if server.state == 'done':
        server.write({'state': 'draft'})
    auth_string = server._generate_outlook_oauth2_string(server.user)
    conn = imaplib.IMAP4_SSL('imap.outlook.com', 993, timeout=30)
    conn.authenticate('XOAUTH2', lambda x: auth_string)
    conn.select('INBOX')
    try:
        process_emails(conn, env, ORDER_KEYWORDS, create_order_record, source='Outlook')
    finally:
        conn.logout()
