import imaplib
import logging

from odoo.addons.smart_billing.utils.imap_shared import INVOICE_KEYWORDS, create_invoice_record, process_emails

_logger = logging.getLogger(__name__)


def acquire_emails_outlook(env):
    accounts = env['smart.billing.outlook.account'].sudo().search([('active', '=', True)])
    for account in accounts:
        try:
            auth_string = account._generate_outlook_oauth2_string(account.email)
            conn = imaplib.IMAP4_SSL('imap.outlook.com', 993, timeout=30)
            conn.authenticate('XOAUTH2', lambda x: auth_string)
            conn.select('INBOX')
            try:
                process_emails(conn, env, INVOICE_KEYWORDS, create_invoice_record, source='Outlook')
            finally:
                conn.logout()
        except Exception as e:
            _logger.error('smart_billing: Outlook acquisition failed for account %r: %s', account.email, e)
