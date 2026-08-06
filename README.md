# Smart Ordering & Smart Billing

Two native Odoo 19 modules that automate the intake of **sales orders** and **supplier invoices** arriving by email — an LLM reads the email/attachment and extracts data, which is then pushed into Odoo (`sale.order` / `account.move`).

Built as an end-of-studies (PFE) project.

---

## 1. Overview

| | `smart_ordering` | `smart_billing` |
|---|---|---|
| Handles | Sales orders | Supplier invoices |
| Source | Email body or attachment (PDF/XLSX/XLS/CSV/TXT) | Email attachment only (PDF/PNG/JPG/JPEG) |
| Extraction | Text-based LLM call (Groq) | Vision-based LLM call (Mistral) |
| Pushes to | `sale.order` | `account.move` (vendor bill) |
| Human review | Draft created automatically, reviewed at Odoo's normal quotation confirm stage. | Required before push |

```
Email inbox (Gmail / Outlook)
        │  IMAP polling, subject containing order/commande/طلب or invoice/facture/فاتورة
        ▼
Acquisition — dedupe by SHA-256 file hash
        ▼
LLM extraction — structured JSON out
        ▼
Human review → validate / Reject → dead end
```

---

## 2. Requirements

- Odoo 19
- Python packages (per-module `requirements.txt`):
  - `smart_ordering`: `pymupdf`, `openpyxl`
  - `smart_billing`: `requests`, `pymupdf`
- A Groq API key (`smart_ordering`) and a Mistral API key (`smart_billing`)
- A Gmail and/or Outlook mailbox to poll

```bash
pip install -r smart_ordering/requirements.txt
pip install -r smart_billing/requirements.txt
```

---

## 3. Installation

1. Drop both module folders into your Odoo `custom-addons` directory (this repo's root *is* that directory).
2. Update the apps list (Settings → developer mode → Apps → Update Apps List).
3. Install **Smart Ordering** and/or **Smart Billing** from the Apps menu, or via command line:
   ```powershell
   docker exec odoo19-footer odoo -i smart_ordering,smart_billing -d automating_odoo --stop-after-init
   ```
   - `smart_ordering` depends on `mail`, `sale`, `microsoft_outlook`.
   - `smart_billing` depends on `mail`, `account`, `microsoft_outlook`.

---

## 4. Configuration

### 4.1 LLM API keys

Set via Settings → Technical → System Parameters (`ir.config_parameter`):

| Module | Key |
|---|---|
| `smart_ordering` | `smart_ordering.groq_api_key` |
| `smart_billing` | `smart_billing.mistral_api_key` |

### 4.2 Email — Gmail

Each module has its own **Gmail Accounts** screen (module menu → Gmail Accounts, admin-only), backed by a dedicated model (`smart.ordering.mail.account` / `smart.billing.mail.account`). One record per mailbox: label, IMAP server/port, email address, Gmail **app password** (not the account password), active toggle.

### 4.3 Email — Outlook

Same pattern as Gmail (`smart.ordering.outlook.account` / `smart.billing.outlook.account`), but OAuth2 instead of a password: enter a label + email, save, then click **Connect your Outlook account**.

Requires one shared Azure app registration, set once before any account can connect — Settings → General Settings → Outlook Credentials, stored as System Parameters (`microsoft_outlook_client_id` / `microsoft_outlook_client_secret`). Same pair is used across every Outlook account on both modules; only the per-mailbox "Connect" step repeats.

### 4.4 Scheduled pipeline

Each module ships its own `ir.cron` job — "Smart Ordering: Run Pipeline" and "Smart Billing: Run Pipeline" — running acquisition → extraction → push-eligibility end to end, every 1 day for both. Adjust from Settings → Technical → Scheduled Actions.

---

## 5. Usage

**`smart_billing`:** invoice arrives → `pending` → `extracted` (LLM ran) → reviewer checks fields against a side-by-side PDF/image preview → **Validate** (creates `account.move`) or **Reject**. Validation is blocked if the supplier name is missing or no line items were extracted.

**`smart_ordering`:** an order email arrives → `pending` → `extracted` (LLM ran) → `pushed` automatically within the same pipeline run, creating a draft `sale.order` (quotation); review happens later, at Odoo's normal quotation confirm stage, same as any manually-entered order.

---

## 6. Docker

Start the stack:
```powershell
docker compose up -d
```

Apply a code change :
```powershell
docker exec odoo19-footer odoo -u smart_ordering,smart_billing -d automating_odoo --stop-after-init
```

Shell access for debugging:
```powershell
docker exec -it odoo19-footer odoo shell -d automating_odoo
```

**Logs:** both modules log through Odoo's standard logger, prefixed by module name — `smart_ordering: ...` / `smart_billing: ...` — so filtering the container log for that prefix isolates everything relevant:
```powershell
docker logs odoo19-footer | Select-String smart_ordering
docker logs odoo19-footer | Select-String smart_billing
```
Warnings and errors are also visible in the UI: Settings → Technical → Database Structure → Logging.
