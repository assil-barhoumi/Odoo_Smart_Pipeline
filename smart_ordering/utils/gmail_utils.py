import imaplib

from odoo.addons.smart_ordering.utils.imap_shared import ORDER_KEYWORDS, create_order_record, process_emails


def acquire_emails(env):
    params = env['ir.config_parameter'].sudo()
    host = params.get_param('smart_ordering.imap_server')
    port = int(params.get_param('smart_ordering.imap_port') or 993)
    user = params.get_param('smart_ordering.imap_email')
    password = params.get_param('smart_ordering.imap_password')
    conn = imaplib.IMAP4_SSL(host, port, timeout=30)
    conn.login(user, password)
    conn.select('INBOX')
    try:
        process_emails(conn, env, ORDER_KEYWORDS, create_order_record, source='Gmail')
    finally:
        conn.logout()
