import base64
import email
import email.header
import email.utils
import logging
import os
from datetime import timezone

_logger = logging.getLogger(__name__)

ORDER_KEYWORDS = ['order', 'commande', 'طلب']

SUPPORTED_EXTENSIONS = {'.pdf', '.xlsx', '.xls', '.csv', '.txt'}


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
    for part in msg.walk():
        raw_filename = part.get_filename()
        if not raw_filename:
            continue
        filename = _decode_subject(raw_filename)
        ext = os.path.splitext(filename)[1].lower()
        if ext not in SUPPORTED_EXTENSIONS:
            return None
        data = part.get_payload(decode=True)
        if data:
            return [{'filename': filename, 'data': data}]
    return []


def create_order_record(env, data):
    if env['smart.order'].sudo().search([('message_id', '=', data['message_id'])], limit=1):
        _logger.debug('smart_ordering [%s]: SKIPPING duplicate message_id=%r', data['source'], data['message_id'])
        return
    _logger.info('smart_ordering [%s]: CREATING record subject=%r sender=%r', data['source'], data['subject'], data['sender'])
    order = env['smart.order'].sudo().create({
        'name': data['subject'],
        'sender_email': data['sender'],
        'email_body': data['body'].strip(),
        'received_at': data['received_at'],
        'source': data['source'].lower(),
        'message_id': data['message_id'],
    })
    for att in data['attachments']:
        env['ir.attachment'].sudo().create({
            'name': att['filename'],
            'datas': base64.b64encode(att['data']).decode(),
            'res_model': 'smart.order',
            'res_id': order.id,
        })
        _logger.info('smart_ordering [%s]: saved attachment %r', data['source'], att['filename'])


def process_emails(conn, env, keywords, create_fn, fetch_body=True, fetch_attachments=False, source=''):
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
            dt = email.utils.parsedate_to_datetime(msg.get('Date', ''))
            received_at = dt.astimezone(timezone.utc).replace(tzinfo=None)
            message_id = msg.get('Message-ID', '').strip()
            attachments = _get_attachments(msg) if fetch_attachments else []
            if attachments is None:
                _logger.warning('smart_ordering [%s]: unsupported attachment format, leaving unread: subject=%r', source, subject)
                continue
            create_fn(env, {
                'subject': subject,
                'sender': sender,
                'received_at': received_at,
                'message_id': message_id,
                'body': _get_plain_body(msg) if fetch_body else '',
                'attachments': attachments,
                'source': source,
            })
            env.cr.commit()
            conn.store(eid, '+FLAGS', '\\Seen')
        except Exception as e:
            _logger.warning('smart_ordering: failed to process email %s: %s', eid, e)
