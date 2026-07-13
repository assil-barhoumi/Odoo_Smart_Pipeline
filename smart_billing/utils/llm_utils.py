import base64
import json
import logging
import os
import re  

_logger = logging.getLogger(__name__)

GROQ_MODEL = 'meta-llama/llama-4-scout-17b-16e-instruct'

PROMPT = """You are an expert financial document extraction assistant specialized in invoices.

Analyze this invoice image carefully. The document may be in French, Arabic, English or a mix.
Extract information based on meaning and context, not exact wording.

FIELD RULES:
- supplier_name: the company or person ISSUING the invoice (selling) — NOT "Bill To", NOT "Ship To"
- supplier_street: full address of the supplier (without country)
- supplier_country: country in English always (Morocco not Maroc, Tunisia not Tunisie, Algeria not Algérie)
- invoice_number: look for "Facture N°", "N° Facture", "Invoice No", "Réf", "رقم الفاتورة"
- date: invoice date, return as YYYY-MM-DD always
- currency: ISO code — DZD, MAD, TND, EUR, USD (DA→DZD, DH→MAD, DT→TND, €→EUR, $→USD). If no symbol, detect from country in address.
- total_ht: subtotal BEFORE tax (HT, Hors Taxe, Montant HT)
- vat_amount: tax amount (TVA, VAT, Tax)
- total_ttc: FINAL total INCLUDING tax (TTC, Total, المجموع)
- Return null for any field that is missing or unclear

NUMERIC RULES — return as plain floats using dot as decimal:
  "6.000,00" → 6000.00
  "1,000.50" → 1000.50
  "1 500,00" → 1500.00
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
  "supplier_country": null,
  "invoice_number": null,
  "date": null,
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
    from groq import Groq

    ext = os.path.splitext(filename)[1].lower()
    if ext == '.pdf':
        import fitz
        doc = fitz.open(stream=data, filetype='pdf')
        img_data = doc[0].get_pixmap(dpi=200).tobytes('png')
        doc.close()
        mime_type = 'image/png'
    elif ext in ('.jpg', '.jpeg'):
        img_data = data
        mime_type = 'image/jpeg'
    else:
        img_data = data
        mime_type = 'image/png'

    encoded = base64.b64encode(img_data).decode('utf-8')
    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{
            'role': 'user',
            'content': [
                {'type': 'image_url', 'image_url': {'url': f'data:{mime_type};base64,{encoded}'}},
                {'type': 'text', 'text': PROMPT},
            ],
        }],
        temperature=0.0,
        max_tokens=8192,
    )

    raw = response.choices[0].message.content or ''
    raw = _strip_json_fences(raw)
    start = raw.find('{')
    if start > 0:
        raw = raw[start:]

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f'Groq returned invalid JSON: {e}\nRaw: {raw[:300]}')

    return result
