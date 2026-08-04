import imaplib
import logging

from odoo.addons.smart_ordering.utils.imap_shared import ORDER_KEYWORDS, create_order_record, process_emails

_logger = logging.getLogger(__name__)


def acquire_emails(env):
    accounts = env['smart.ordering.mail.account'].sudo().search([('active', '=', True)])
    own_addresses = {a.email.lower() for a in accounts if a.email}
    if env.company.email:
        own_addresses.add(env.company.email.lower())
    for account in accounts:
        try:
            conn = imaplib.IMAP4_SSL(account.server, account.port, timeout=30)
            conn.login(account.email, account.password)
            conn.select('INBOX')
            try:
                process_emails(conn, env, ORDER_KEYWORDS, create_order_record, fetch_attachments=True, source='Gmail', own_addresses=own_addresses)
            finally:
                conn.logout()
        except Exception as e:
            _logger.error('smart_ordering: Gmail acquisition failed for account %r: %s', account.email, e)
