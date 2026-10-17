import base64
import json
import logging
import os
import re
import time

import requests

_logger = logging.getLogger(__name__)

KIMI_MODEL = 'kimi-k3'
KIMI_URL = 'https://ws-63fod20c1h3he9ol.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1/chat/completions'


class QuotaExceeded(Exception):
    pass


class AuthenticationError(Exception):
    """The API key was rejected. Retrying won't help until it's fixed in settings."""


def _is_quota_error(response):
    try:
        err = response.json().get('error', {})
    except ValueError:
        return False
    text = f"{err.get('code', '')} {err.get('type', '')} {err.get('message', '')}".lower()
    return any(s in text for s in ('insufficient_quota', 'exceeded your current quota', 'credit balance is too low'))


def _post_with_retry(url, headers, payload, max_retries=2):
    for attempt in range(1, max_retries + 2):
        response = requests.post(url, headers=headers, json=payload, timeout=90)
        if response.status_code in (401, 403):
            raise AuthenticationError(f'Kimi K3 rejected the API key ({response.status_code}): {response.text[:200]}')
        if response.status_code in (429, 400) and _is_quota_error(response):
            raise QuotaExceeded(f'billing/quota issue, not a rate limit: {response.text[:200]}')
        if response.status_code in (429, 502, 503, 504):
            if attempt > max_retries:
                response.raise_for_status()
            wait = float(response.headers.get('Retry-After') or min(2 ** attempt, 20))
            _logger.warning('smart_billing: %s from Kimi K3, retrying in %.0fs (attempt %d/%d)',
                             response.status_code, wait, attempt, max_retries)
            time.sleep(wait)
            continue
        response.raise_for_status()
        return response

PROMPT = """You are an expert financial document extraction assistant specialized in invoices.

Analyze this invoice carefully. You may be given more than one image — if so, they are consecutive
pages of the SAME invoice, in order, not separate documents. Combine information across all pages:
header/supplier/totals fields may appear on any page, and line items may continue across pages —
extract every line item from every page, do not stop after the first page.
The document may be in French, Arabic, English or a mix.
Extract information based on meaning and context, not exact wording.

FIELD RULES:
- supplier_name: the company or person ISSUING the invoice (selling) — NOT "Bill To", NOT "Ship To"
- supplier_street: street/building-level address of the supplier only (without city, postal code, or country, and without field labels like "Code postal:" — those go in their own fields below)
- supplier_city: the supplier's city, exactly as printed. Null if not present.
- supplier_zip: the supplier's postal code, digits only, no label text (e.g. "40000" not "Code postal: 40 000"). Null if not present.
- supplier_country: country in English always (Morocco not Maroc, Tunisia not Tunisie, Algeria not Algérie)
- supplier_phone: phone number, exactly as printed. On Arabic/RTL documents, digit groups may appear visually reversed — reconstruct left-to-right order (the "+" country code comes first).
- supplier_tax_id: supplier's national business/tax identifier, exactly as printed — e.g. Morocco's "ICE", Tunisia's "Matricule Fiscal", a VAT/TVA number, or equivalent. Null if not present.
- supplier_bank_account: the supplier's IBAN or bank account number for payment, exactly as printed (keep spaces). Look for "IBAN", "RIB", "Compte N°", "Account No". Null if not present.
- supplier_bank_name: the bank/branch name (e.g. "BNA — Agence Sousse"). Never return the field label itself (e.g. "Bank Account"/"الحساب البنكي") — extract the actual bank name next to it.
- invoice_number: look for "Facture N°", "N° Facture", "Invoice No", "Réf", "رقم الفاتورة"
- date: invoice date, return as YYYY-MM-DD always
- due_date: payment due date ("Échéance", "Date d'échéance", "Due Date", "تاريخ الاستحقاق"), return as YYYY-MM-DD, null if not present — do NOT copy the invoice date into this field
- currency: ISO code — DZD, MAD, TND, EUR, USD (DA→DZD, DH→MAD, DT→TND, €→EUR, $→USD). If no symbol, detect from country in address.
- total_ht: subtotal BEFORE tax (HT, Hors Taxe, Montant HT)
- vat_amount: tax amount (TVA, VAT, Tax)
- total_ttc: FINAL total INCLUDING tax (TTC, Total, المجموع)
- Return null for any field that is missing or unclear

NUMERIC RULES — return as plain floats using dot as decimal:
  "1,000.50" → 1000.50
  "7.993,878" → 7993.878
  Remove all currency symbols and spaces from numbers

LINE ITEMS RULES:
- Extract ALL rows from the table
- IGNORE summary rows (Total, TVA, HT, Remise, Discount)
- If quantity is missing use 1.0
- If unit_price is missing but total is present, use total
- item_type: "product" if it is a physical good, "service" if it is a service

Return ONLY this valid JSON, no explanation, no markdown:
{
  "supplier_name": null,
  "supplier_street": null,
  "supplier_city": null,
  "supplier_zip": null,
  "supplier_country": null,
  "supplier_phone": null,
  "supplier_tax_id": null,
  "supplier_bank_account": null,
  "supplier_bank_name": null,
  "invoice_number": null,
  "date": null,
  "due_date": null,
  "line_items": [
    {
      "description": null,
      "quantity": null,
      "unit_price": null,
      "total_line": null,
      "item_type": null
    }
  ],
  "total_ht": null,
  "vat_amount": null,
  "total_ttc": null,
  "currency": null,
  "confidence": 0.0
}

confidence rules:
- 0.9-1.0: all fields clear and certain
- 0.7-0.9: most fields clear, minor uncertainty
- 0.4-0.7: partial or ambiguous document
- below 0.4: unreadable or too incomplete"""


def _strip_json_fences(text):
    text = re.sub(r'^```(?:json)?\s*', '', text.strip())
    text = re.sub(r'\s*```$', '', text.strip())
    return text


def extract_invoice(data, filename, api_key):
    ext = os.path.splitext(filename)[1].lower()
    images = []
    if ext == '.pdf':
        import fitz
        doc = fitz.open(stream=data, filetype='pdf')
        for page in doc:
            images.append((page.get_pixmap(dpi=200).tobytes('png'), 'image/png'))
        doc.close()
    elif ext in ('.jpg', '.jpeg'):
        images.append((data, 'image/jpeg'))
    else:
        images.append((data, 'image/png'))

    content = [
        {'type': 'image_url', 'image_url': {'url': f'data:{mime_type};base64,{base64.b64encode(img_data).decode("utf-8")}'}}
        for img_data, mime_type in images
    ]
    content.append({'type': 'text', 'text': PROMPT})

    payload = {
        'model': KIMI_MODEL,
        'messages': [{
            'role': 'user',
            'content': content,
        }],
        'temperature': 0.0,
        'max_tokens': 8192,
    }
    response = _post_with_retry(
        KIMI_URL,
        headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'},
        payload=payload,
    )
    body = response.json()

    raw = body['choices'][0]['message']['content'] or ''
    raw = _strip_json_fences(raw)
    start = raw.find('{')
    if start > 0:
        raw = raw[start:]

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f'Kimi K3 returned invalid JSON: {e}\nRaw: {raw[:300]}')

    return result
