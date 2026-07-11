import imaplib

from odoo.addons.smart_billing.utils.imap_shared import INVOICE_KEYWORDS, create_invoice_record, process_emails


def acquire_emails(env):
    params = env['ir.config_parameter'].sudo()
    host = params.get_param('smart_billing.imap_server')
    port = int(params.get_param('smart_billing.imap_port') or 993)
    user = params.get_param('smart_billing.imap_email')
    password = params.get_param('smart_billing.imap_password')
    conn = imaplib.IMAP4_SSL(host, port, timeout=30)
    conn.login(user, password)
    conn.select('INBOX')
    try:
        process_emails(conn, env, INVOICE_KEYWORDS, create_invoice_record, source='Gmail')
    finally:
        conn.logout()
