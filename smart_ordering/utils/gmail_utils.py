import email
import email.header
import email.utils
import imaplib
import logging
from datetime import timezone

_logger = logging.getLogger(__name__)

ORDER_KEYWORDS = ['order', 'commande', 'طلب']

def _decode_subject(raw):
    parts = email.header.decode_header(raw)
    return ''.join(
        p.decode(c or 'utf-8', errors='ignore') if isinstance(p, bytes) else p
        for p, c in parts
    )

def _get_plain_body(msg):
    for part in msg.walk():
        if (part.get_content_type() == 'text/plain'
                and 'attachment' not in str(part.get('Content-Disposition'))):
            return part.get_payload(decode=True).decode('utf-8', errors='ignore')
    return ''

def acquire_emails(env):
    params = env['ir.config_parameter'].sudo()
    host = params.get_param('smart_ordering.imap_server')
    port = int(params.get_param('smart_ordering.imap_port') or 993)
    user = params.get_param('smart_ordering.imap_email')
    password = params.get_param('smart_ordering.imap_password')

    conn = imaplib.IMAP4_SSL(host, port, timeout=30)
    conn.login(user, password)
    conn.select('INBOX')

    _, data = conn.search(None, 'UNSEEN')
    for eid in data[0].split():
        try:
            _, hdr_data = conn.fetch(eid, '(BODY.PEEK[HEADER.FIELDS (SUBJECT)])')
            hdr = email.message_from_bytes(hdr_data[0][1])
            subject = _decode_subject(hdr.get('Subject', ''))
            if not any(kw in subject.lower() for kw in ORDER_KEYWORDS):
                continue
            _, msg_data = conn.fetch(eid, '(BODY.PEEK[])')
            msg = email.message_from_bytes(msg_data[0][1])
            _, sender_addr = email.utils.parseaddr(msg.get('From', ''))
            body = _get_plain_body(msg)
            dt = email.utils.parsedate_to_datetime(msg.get('Date', ''))
            received_at = dt.astimezone(timezone.utc).replace(tzinfo=None)
            _logger.info('smart_ordering: CREATING record subject=%r sender=%r', subject, sender_addr)
            env['smart.order'].sudo().create({
                'name': subject,
                'sender_email': sender_addr,
                'email_body': body.strip(),
                'received_at': received_at,
            })
            env.cr.commit()
            conn.store(eid, '+FLAGS', '\\Seen')
        except Exception as e:
            _logger.warning('smart_ordering: failed to process email %s: %s', eid, e)

    conn.logout()
