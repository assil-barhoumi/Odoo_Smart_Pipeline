import imaplib
import logging

from odoo.addons.smart_ordering.utils.imap_shared import ORDER_KEYWORDS, create_order_record, process_emails

_logger = logging.getLogger(__name__)


def acquire_emails_outlook(env):
    accounts = env['smart.ordering.outlook.account'].sudo().search([('active', '=', True)])
    own_addresses = {a.email.lower() for a in accounts if a.email}
    if env.company.email:
        own_addresses.add(env.company.email.lower())
    for account in accounts:
        try:
            auth_string = account._generate_outlook_oauth2_string(account.email)
            conn = imaplib.IMAP4_SSL('imap.outlook.com', 993, timeout=30)
            conn.authenticate('XOAUTH2', lambda x: auth_string)
            conn.select('INBOX')
            try:
                process_emails(conn, env, ORDER_KEYWORDS, create_order_record, fetch_attachments=True, source='Outlook', own_addresses=own_addresses)
            finally:
                conn.logout()
        except Exception as e:
            _logger.error('smart_ordering: Outlook acquisition failed for account %r: %s', account.email, e)
