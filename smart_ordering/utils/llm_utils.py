import json
import re
import requests

QWEN_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions"
QWEN_MODEL = "qwen-plus"


class AuthenticationError(Exception):
    """The API key was rejected. Retrying won't help until it's fixed in settings."""


_PROMPT = """You are an expert order extraction assistant.

Extract structured data from this order email. The email may be in any language (French, Arabic, English, or mixed).

The input may contain an EMAIL BODY section and one or more ATTACHMENT sections, separated by "---".

Rules:
- client_name: buyer name if mentioned, otherwise null.
- line_items: extract ALL products/services mentioned. Never skip a product even if quantity is missing — return null for missing quantity.
- source: for each line item, set this to ONLY the filename if it came from an attachment (e.g. "invoice.pdf" — never include the words "ATTACHMENT" or parentheses), or the literal string "EMAIL BODY" if it came from the email body. If an item was mentioned in more than one source, use the source whose quantity was kept per the duplicate rule below.
- The EMAIL BODY often adds information not present in any attachment — extra items, delivery instructions, urgency, special requests. Always read it, don't treat it as a mere wrapper around the attachments.
- If the same item appears in both the email body and an attachment (or in more than one attachment), extract it ONLY ONCE — do not add its quantity twice. Treat attachment content as authoritative over the body when they describe the same item. If the same item has different quantities in different sources, use the quantity from the LAST attachment it appears in — apply this rule silently, do not explain the discrepancy.
- suspected_multi_order: set to true ONLY if the attachments appear to describe genuinely separate, unrelated orders (e.g. different client names, unrelated item sets with no shared context) rather than one order split across supporting files. Default to false — most multi-attachment emails are one order with supporting documents, not multiple bundled orders.
- notes: any additional instructions, delivery requests, or context.

Do not explain your reasoning, do not add commentary, do not describe how you resolved duplicates or conflicts. Output the JSON object directly, with no preamble or text before or after it.

Return ONLY this JSON:
{
  "client_name": string or null,
  "line_items": [
    {"description": string, "quantity": float or null, "source": string}
  ],
  "notes": string or null,
  "suspected_multi_order": boolean,
  "confidence": float (0.0 to 1.0)
}

confidence score rules:
- 0.9-1.0: email is a clear order, all key fields extracted with certainty
- 0.7-0.9: most fields clear, minor uncertainty on some values
- 0.4-0.6: email is ambiguous or several fields are unclear
- below 0.4: email is too incomplete or unclear to trust"""


def strip_json_fences(text: str) -> str:
    text = re.sub(r'^```(?:json)?\s*', '', text.strip())
    text = re.sub(r'\s*```$',          '', text.strip())
    return text


def extract_order(email_body: str, api_key: str) -> dict:
    payload = {
        "model": QWEN_MODEL,
        "messages": [{"role": "user", "content": f"{_PROMPT}\n\nEMAIL:\n{email_body}"}],
        "temperature": 0.0,
        "max_tokens": 1024,
        "response_format": {"type": "json_object"},
    }
    response = requests.post(
        QWEN_URL,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        json=payload,
        timeout=60,
    )
    if response.status_code in (401, 403):
        raise AuthenticationError(f'Qwen rejected the API key ({response.status_code}): {response.text[:200]}')
    response.raise_for_status()
    raw_text = response.json()["choices"][0]["message"]["content"]
    raw_text = strip_json_fences(raw_text)
    result = json.loads(raw_text)
    result.setdefault("client_name", None)
    result.setdefault("notes", None)
    result.setdefault("confidence", 0.0)
    result["suspected_multi_order"] = bool(result.get("suspected_multi_order"))
    if not isinstance(result.get("line_items"), list):
        result["line_items"] = []
    for item in result["line_items"]:
        item.setdefault("source", None)
    return result
