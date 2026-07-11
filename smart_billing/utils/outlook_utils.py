import imaplib
import logging

from odoo.addons.smart_billing.utils.imap_shared import INVOICE_KEYWORDS, create_invoice_record, process_emails

_logger = logging.getLogger(__name__)


def acquire_emails_outlook(env):
    server = env['fetchmail.server'].sudo().search([
        ('server_type', '=', 'outlook'),
        ('active', '=', True),
    ], limit=1)
    if not server:
        return
    if server.state == 'done':
        try:
            with server.env.cr.savepoint():
                server.write({'state': 'draft'})
        except Exception as e:
            _logger.warning('smart_billing: could not reset fetchmail state: %s', e)
    auth_string = server._generate_outlook_oauth2_string(server.user)
    conn = imaplib.IMAP4_SSL('imap.outlook.com', 993, timeout=30)
    conn.authenticate('XOAUTH2', lambda x: auth_string)
    conn.select('INBOX')
    try:
        process_emails(conn, env, INVOICE_KEYWORDS, create_invoice_record, source='Outlook')
    finally:
        conn.logout()
