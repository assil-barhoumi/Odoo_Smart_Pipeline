import json
import re
import requests

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"

_PROMPT = """You are an expert order extraction assistant.

Extract structured data from this order email. The email may be in any language (French, Arabic, English, or mixed).

Rules:
- client_name: buyer name if mentioned, otherwise null.
- line_items: extract ALL products/services mentioned. Never skip a product even if quantity is missing — return null for missing quantity.
- notes: any additional instructions, delivery requests, or context.

Return ONLY this JSON:
{
  "client_name": string or null,
  "line_items": [
    {"description": string, "quantity": float or null}
  ],
  "notes": string or null,
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
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": f"{_PROMPT}\n\nEMAIL:\n{email_body}"}],
        "temperature": 0.0,
        "max_tokens": 1024,
    }
    response = requests.post(
        GROQ_URL,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        json=payload,
        timeout=60,
    )
    response.raise_for_status()
    raw_text = response.json()["choices"][0]["message"]["content"]
    raw_text = strip_json_fences(raw_text)
    result = json.loads(raw_text)
    result.setdefault("client_name", None)
    result.setdefault("notes", None)
    result.setdefault("confidence", 0.0)
    if not isinstance(result.get("line_items"), list):
        result["line_items"] = []
    return result
