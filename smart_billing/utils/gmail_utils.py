import imaplib
import logging

from odoo.addons.smart_billing.utils.imap_shared import INVOICE_KEYWORDS, create_invoice_record, process_emails

_logger = logging.getLogger(__name__)


def acquire_emails(env):
    accounts = env['smart.billing.mail.account'].sudo().search([('active', '=', True)])
    own_addresses = {a.email.lower() for a in accounts if a.email}
    if env.company.email:
        own_addresses.add(env.company.email.lower())
    for account in accounts:
        try:
            conn = imaplib.IMAP4_SSL(account.server, account.port, timeout=30)
            conn.login(account.email, account.password)
            conn.select('INBOX')
            try:
                process_emails(conn, env, INVOICE_KEYWORDS, create_invoice_record, source='Gmail', own_addresses=own_addresses, recipient_email=account.email)
            finally:
                conn.logout()
        except Exception as e:
            _logger.error('smart_billing: Gmail acquisition failed for account %r: %s', account.email, e)
