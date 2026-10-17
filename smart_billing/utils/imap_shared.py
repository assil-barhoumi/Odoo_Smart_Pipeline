import base64
import email
import email.header
import email.utils
import hashlib
import logging
import os
from datetime import timezone

_logger = logging.getLogger(__name__)

INVOICE_KEYWORDS = ['invoice', 'facture', 'فاتورة']
SUPPORTED_EXTENSIONS = {'.pdf', '.png', '.jpg', '.jpeg'}


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

def _get_attachments(msg):
    result = []
    for part in msg.walk():
        raw_filename = part.get_filename()
        if not raw_filename:
            continue
        filename = _decode_subject(raw_filename)
        ext = os.path.splitext(filename)[1].lower()
        if ext not in SUPPORTED_EXTENSIONS:
            continue
        data = part.get_payload(decode=True)
        if data:
            result.append({'filename': filename, 'data': data})
    return result

def create_invoice_record(env, data):
    if not data['attachments']:
        return

    for att in data['attachments']:
        with env.cr.savepoint():
            file_hash = hashlib.sha256(att['data']).hexdigest()

            if env['smart.invoice'].sudo().search([('file_hash', '=', file_hash)], limit=1):
                continue

            _logger.info('smart_billing [%s]: creating record file=%r sender=%r', data['source'], att['filename'], data['sender'])
            invoice = env['smart.invoice'].sudo().create({
                'file_name': att['filename'],
                'file_hash': file_hash,
                'sender_email': data['sender'],
                'email_body': data['body'].strip(),
                'received_at': data['received_at'],
                'source': data['source'].lower(),
                'message_id': data['message_id'],
                'recipient_email': data.get('recipient_email'),
            })
            env['ir.attachment'].sudo().create({
                'name': att['filename'],
                'datas': base64.b64encode(att['data']).decode(),
                'res_model': 'smart.invoice',
                'res_id': invoice.id,
            })

def process_emails(conn, env, keywords, create_fn, source='', own_addresses=None, recipient_email=None):
    own_addresses = own_addresses or set()
    _, data = conn.search(None, 'UNSEEN')
    for eid in data[0].split():
        try:
            _, hdr_data = conn.fetch(eid, '(BODY.PEEK[HEADER.FIELDS (SUBJECT)])')
            hdr = email.message_from_bytes(hdr_data[0][1])
            subject = _decode_subject(hdr.get('Subject', ''))
            if not any(kw in subject.lower() for kw in keywords):
                continue
            _, msg_data = conn.fetch(eid, '(BODY.PEEK[])')
            msg = email.message_from_bytes(msg_data[0][1])
            _, sender = email.utils.parseaddr(msg.get('From', ''))
            if sender.lower() in own_addresses:
                _logger.info('smart_billing [%s]: SKIPPING self-sent email (sender=%r matches our own configured address) subject=%r', source, sender, subject)
                conn.store(eid, '+FLAGS', '\\Seen')
                continue
            dt = email.utils.parsedate_to_datetime(msg.get('Date', ''))
            received_at = dt.astimezone(timezone.utc).replace(tzinfo=None)
            message_id = msg.get('Message-ID', '').strip()
            attachments = _get_attachments(msg)
            create_fn(env, {
                'subject': subject,
                'sender': sender,
                'received_at': received_at,
                'message_id': message_id,
                'body': _get_plain_body(msg),
                'attachments': attachments,
                'source': source,
                'recipient_email': recipient_email,
            })
            env.cr.commit()
            conn.store(eid, '+FLAGS', '\\Seen')
        except Exception as e:
            _logger.warning('smart_billing: failed to process email %s: %s', eid, e)
