import base64
import hashlib
import json
import logging

from odoo import api, models, fields
from odoo.exceptions import ValidationError
from odoo.addons.smart_billing.utils.gmail_utils import acquire_emails
from odoo.addons.smart_billing.utils.outlook_utils import acquire_emails_outlook
from odoo.addons.smart_billing.utils.llm_utils import extract_invoice, AuthenticationError, QuotaExceeded

_logger = logging.getLogger(__name__)

EXTRACTION_MAX_ATTEMPTS = 2


class SmartInvoiceLine(models.Model):
    _name = 'smart.invoice.line'
    _description = 'Smart Invoice Line'

    invoice_id = fields.Many2one('smart.invoice', ondelete='cascade', required=True)
    description = fields.Text()
    quantity = fields.Float(digits=(16, 4))
    unit_price = fields.Float(digits=(16, 4))
    total_line = fields.Float(digits=(16, 4))
    item_type = fields.Char()


class SmartInvoice(models.Model):
    _name = 'smart.invoice'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Smart Invoice'
    _rec_name = 'file_name'
    _order = 'received_at desc'

    sender_email = fields.Char(string='Sender', readonly=True)
    recipient_email = fields.Char(string='Recipient', readonly=True, help='Mailbox address that received this invoice.')
    email_body = fields.Text(string='Email Body', readonly=True)
    received_at = fields.Datetime(string='Received At', readonly=True)
    source = fields.Selection([
        ('gmail', 'Gmail'),
        ('outlook', 'Outlook'),
    ], string='Source', readonly=True)
    message_id = fields.Char(string='Message-ID', readonly=True, index=True)
    # Display-only, collision-tolerant hash of message_id. Never use for identity/dedup checks — use message_id instead.
    message_id_short = fields.Char(
        string='Email Ref', compute='_compute_message_id_short', store=True,
        help='Short reference derived from Message-ID, for display only — not a unique identifier.',
    )
    file_name = fields.Char(string='Attachment', required=True, readonly=True)
    file_hash = fields.Char(string='File Hash', readonly=True, index=True)
    invoice_file = fields.Binary(string='Invoice Preview', readonly=True, attachment=True)
    is_pdf = fields.Boolean(string='Is PDF', compute='_compute_is_pdf', store=True)

    supplier_name = fields.Char(string='Supplier')
    supplier_street = fields.Char(string='Supplier Address')
    supplier_city = fields.Char(string='Supplier City')
    supplier_zip = fields.Char(string='Supplier Postal Code')
    supplier_country = fields.Char(string='Supplier Country')
    supplier_phone = fields.Char(string='Supplier Phone')
    supplier_tax_id = fields.Char(string='Supplier Tax ID', help='National business/tax identifier: ICE (Morocco), Matricule Fiscal (Tunisia), VAT number, or equivalent.')
    supplier_bank_account = fields.Char(string='Recipient Bank Account', help='IBAN or bank account number, exactly as printed on the invoice.')
    supplier_bank_name = fields.Char(string='Recipient Bank Name')
    bank_account_valid = fields.Boolean(compute='_compute_bank_account_valid', string='Bank Account Looks Valid')
    show_additional_info = fields.Boolean(string='Show Additional Info', default=False, help='UI toggle only, not extracted data.')
    has_missing_info = fields.Boolean(compute='_compute_has_missing_info')
    invoice_number = fields.Char(string='Invoice Number')
    invoice_date = fields.Date(string='Invoice Date')
    due_date = fields.Date(string='Due Date')
    total_ht = fields.Float(string='Total HT', digits=(16, 3))
    vat_amount = fields.Float(string='VAT Amount', digits=(16, 3))
    total_ttc = fields.Float(string='Total TTC', digits=(16, 3))
    currency_code = fields.Char(string='Currency')
    line_ids = fields.One2many('smart.invoice.line', 'invoice_id', string='Line Items')

    confidence = fields.Float(string='Confidence', readonly=True)
    # Display-only: Odoo's progressbar widget treats max_value as a field lookup, never a literal
    # number, so a plain 0-100 field is needed to make the bar render correctly against a 0.0-1.0 confidence.
    confidence_pct = fields.Integer(string='Confidence %', compute='_compute_confidence_pct')
    extracted_error = fields.Char(string='Extraction Error', readonly=True)
    extracted_json = fields.Text(string='Extracted Data', readonly=True)

    status = fields.Selection([
        ('pending', 'Pending'),
        ('extracted', 'Extracted'),
        ('validated', 'Validated'),
        ('pushed', 'Pushed'),
        ('rejected', 'Rejected'),
        ('failed', 'Failed'),
    ], string='Status', default='pending', required=True, tracking=True, index=True)
    move_id = fields.Many2one(
        'account.move',
        string='Vendor Bill',
        readonly=True,
        ondelete='set null',
    )

    supplier_info_changed = fields.Boolean(compute='_compute_supplier_info_diff')
    supplier_info_diff = fields.Text(compute='_compute_supplier_info_diff')

    @api.depends('file_name')
    def _compute_is_pdf(self):
        for rec in self:
            rec.is_pdf = bool(rec.file_name) and rec.file_name.lower().endswith('.pdf')

    @api.depends('message_id')
    def _compute_message_id_short(self):
        for rec in self:
            rec.message_id_short = (
                hashlib.md5(rec.message_id.encode()).hexdigest()[:8]
                if rec.message_id else False
            )

    @api.depends('confidence')
    def _compute_confidence_pct(self):
        for rec in self:
            rec.confidence_pct = round((rec.confidence or 0.0) * 100)

    @api.depends('supplier_bank_account')
    def _compute_bank_account_valid(self):
        Bank = self.env['res.partner.bank']
        for rec in self:
            rec.bank_account_valid = bool(rec.supplier_bank_account) and Bank.check_iban(rec.supplier_bank_account)

    @api.depends('supplier_name', 'supplier_street', 'supplier_city', 'supplier_zip', 'supplier_country',
                 'supplier_phone', 'supplier_tax_id', 'supplier_bank_account', 'bank_account_valid',
                 'invoice_number', 'invoice_date', 'due_date', 'currency_code')
    def _compute_has_missing_info(self):
        for rec in self:
            rec.has_missing_info = not all([
                rec.supplier_name, rec.supplier_street, rec.supplier_city, rec.supplier_zip,
                rec.supplier_country, rec.supplier_phone,
                rec.supplier_tax_id, rec.supplier_bank_account and rec.bank_account_valid,
                rec.invoice_number, rec.invoice_date, rec.due_date, rec.currency_code,
            ])

    @api.depends('supplier_name', 'supplier_street', 'supplier_city', 'supplier_zip',
                 'supplier_country', 'supplier_phone', 'supplier_tax_id',
                 'supplier_bank_account', 'bank_account_valid')
    def _compute_supplier_info_diff(self):
        for rec in self:
            rec.supplier_info_changed = False
            rec.supplier_info_diff = False
            if not rec.supplier_name:
                continue
            partner = self.env['res.partner'].sudo().search([('name', '=ilike', rec.supplier_name)], limit=1)
            if not partner:
                continue
            diffs = []
            if (rec.supplier_street or '') != (partner.street or ''):
                diffs.append('Address: "%s" → "%s"' % (partner.street or '(empty)', rec.supplier_street or '(empty)'))
            if (rec.supplier_city or '') != (partner.city or ''):
                diffs.append('City: "%s" → "%s"' % (partner.city or '(empty)', rec.supplier_city or '(empty)'))
            if (rec.supplier_zip or '') != (partner.zip or ''):
                diffs.append('Postal Code: "%s" → "%s"' % (partner.zip or '(empty)', rec.supplier_zip or '(empty)'))
            partner_country = partner.country_id.name or ''
            if (rec.supplier_country or '') != partner_country:
                diffs.append('Country: "%s" → "%s"' % (partner_country or '(empty)', rec.supplier_country or '(empty)'))
            if (rec.supplier_phone or '') != (partner.phone or ''):
                diffs.append('Phone: "%s" → "%s"' % (partner.phone or '(empty)', rec.supplier_phone or '(empty)'))
            if (rec.supplier_tax_id or '') != (partner.vat or ''):
                diffs.append('Tax ID: "%s" → "%s"' % (partner.vat or '(empty)', rec.supplier_tax_id or '(empty)'))
            if rec.supplier_bank_account and rec.bank_account_valid and partner.bank_ids:
                new_acc = rec.supplier_bank_account.replace(' ', '').upper()
                existing_accs = [(b.acc_number or '').replace(' ', '').upper() for b in partner.bank_ids]
                if new_acc not in existing_accs:
                    diffs.append('Bank Account: "%s" → "%s"' % (
                        ', '.join(partner.bank_ids.mapped('acc_number')) or '(empty)', rec.supplier_bank_account))
            if diffs:
                rec.supplier_info_changed = True
                rec.supplier_info_diff = '\n'.join(diffs)

    def _acquire_emails(self):
        try:
            acquire_emails(self.env)
        except Exception as e:
            _logger.error('smart_billing: Gmail acquisition failed: %s', e)
        try:
            acquire_emails_outlook(self.env)
        except Exception as e:
            _logger.error('smart_billing: Outlook acquisition failed: %s', e)

    def _run_pipeline(self):
        try:
            self._acquire_emails()
        except Exception as e:
            _logger.error('smart_billing: acquisition failed: %s', e)
        self.env.invalidate_all()
        self.search([('status', '=', 'pending')])._run_extraction()

    def action_run_extraction(self):
        self.check_access_rights('write')
        self._run_extraction()

    def action_reset_to_pending(self):
        self.write({'status': 'pending', 'extracted_error': False})

    def _run_extraction(self):
        settings = self.env['smart.billing.settings'].sudo().search([], limit=1)
        api_key = settings.mistral_api_key if settings else False
        if not api_key:
            _logger.error('smart_billing: kimi_api_key not configured')
            return

        for invoice in self:
            attachment = self.env['ir.attachment'].sudo().search([
                ('res_model', '=', 'smart.invoice'),
                ('res_id', '=', invoice.id),
            ], limit=1)
            if not attachment:
                continue
            data = base64.b64decode(attachment.datas)

            error = None
            stop_batch = False
            for attempt in range(EXTRACTION_MAX_ATTEMPTS):
                try:
                    result = extract_invoice(data, attachment.name, api_key)

                    line_items = result.get('line_items') or []
                    line_cmds = [(0, 0, {
                        'description': item.get('description') or '',
                        'quantity': float(item.get('quantity') or 1.0),
                        'unit_price': float(item.get('unit_price') or 0.0),
                        'total_line': float(item.get('total_line') or 0.0),
                        'item_type': item.get('item_type') or '',
                    }) for item in line_items]

                    invoice.sudo().write({
                        'invoice_file': attachment.datas,
                        'supplier_name': result.get('supplier_name'),
                        'supplier_street': result.get('supplier_street'),
                        'supplier_city': result.get('supplier_city'),
                        'supplier_zip': result.get('supplier_zip'),
                        'supplier_country': result.get('supplier_country'),
                        'supplier_phone': result.get('supplier_phone'),
                        'supplier_tax_id': result.get('supplier_tax_id'),
                        'supplier_bank_account': result.get('supplier_bank_account'),
                        'supplier_bank_name': result.get('supplier_bank_name'),
                        'invoice_number': result.get('invoice_number'),
                        'invoice_date': result.get('date'),
                        'due_date': result.get('due_date'),
                        'total_ht': result.get('total_ht'),
                        'vat_amount': result.get('vat_amount'),
                        'total_ttc': result.get('total_ttc'),
                        'currency_code': result.get('currency'),
                        'confidence': result.get('confidence', 0.0),
                        'extracted_error': False,
                        'extracted_json': json.dumps(result, ensure_ascii=False),
                        'status': 'extracted',
                        'line_ids': line_cmds,
                    })
                    _logger.info('smart_billing: extracted %s confidence=%.2f', invoice.file_name, result.get('confidence', 0.0))
                    error = None
                    break
                except (AuthenticationError, QuotaExceeded) as e:
                    # Not this document's fault — the key or the account's quota is the
                    # problem, retrying it, or any other record in this batch, won't help.
                    error = e
                    stop_batch = True
                    break
                except Exception as e:
                    error = e
                    _logger.warning('smart_billing: extraction attempt %d/%d failed for %s: %s',
                                     attempt + 1, EXTRACTION_MAX_ATTEMPTS, invoice.file_name, e)
            if error:
                invoice.sudo().write({'status': 'failed', 'extracted_error': str(error)})
            if stop_batch:
                _logger.error('smart_billing: stopping extraction batch: %s', error)
                break

    def _get_or_create_partner(self):
        self.ensure_one()
        partner = False
        if self.supplier_tax_id:
            partner = self.env['res.partner'].sudo().search([('vat', '=', self.supplier_tax_id)], limit=1)
        if not partner:
            partner = self.env['res.partner'].sudo().search([('name', '=ilike', self.supplier_name)], limit=1)
        if partner:
            if self.supplier_tax_id and not partner.vat:
                partner.sudo().write({'vat': self.supplier_tax_id})
            return partner

        country = False
        if self.supplier_country:
            country = self.env['res.country'].sudo().search([('name', 'ilike', self.supplier_country)], limit=1)

        return self.env['res.partner'].sudo().create({
            'name': self.supplier_name,
            'supplier_rank': 1,
            'street': self.supplier_street or False,
            'city': self.supplier_city or False,
            'zip': self.supplier_zip or False,
            'country_id': country.id if country else False,
            'email': self.sender_email or False,
            'phone': self.supplier_phone or False,
            'vat': self.supplier_tax_id or False,
        })

    def _get_currency(self):
        self.ensure_one()
        if not self.currency_code:
            return False
        currency = self.env['res.currency'].sudo().with_context(active_test=False).search(
            [('name', '=', self.currency_code.upper())], limit=1
        )
        if currency and not currency.active:
            currency.sudo().write({'active': True})
        return currency

    def _get_or_create_bank_account(self, partner):
        self.ensure_one()
        if not self.supplier_bank_account:
            return False
        Bank = self.env['res.partner.bank'].sudo()
        account = Bank.search([
            ('partner_id', '=', partner.id),
            ('acc_number', '=', self.supplier_bank_account),
        ], limit=1)
        if account:
            return account
        bank_id = False
        if self.supplier_bank_name:
            bank = self.env['res.bank'].sudo().search([('name', '=ilike', self.supplier_bank_name)], limit=1)
            if not bank:
                bank = self.env['res.bank'].sudo().create({'name': self.supplier_bank_name})
            bank_id = bank.id
        try:
            with self.env.cr.savepoint():
                return Bank.create({
                    'partner_id': partner.id,
                    'acc_number': self.supplier_bank_account,
                    'bank_id': bank_id,
                })
        except Exception as e:
            _logger.warning('smart_billing: failed to create bank account for partner %s: %s', partner.id, e)
            return False

    def action_update_supplier_info(self):
        self.ensure_one()
        self.check_access_rights('write')
        if not self.supplier_name:
            return
        partner = self.env['res.partner'].sudo().search([('name', '=ilike', self.supplier_name)], limit=1)
        if not partner:
            return
        country = False
        if self.supplier_country:
            country = self.env['res.country'].sudo().search([('name', 'ilike', self.supplier_country)], limit=1)
        partner.sudo().write({
            'street': self.supplier_street or partner.street,
            'city': self.supplier_city or partner.city,
            'zip': self.supplier_zip or partner.zip,
            'country_id': country.id if country else partner.country_id.id,
            'phone': self.supplier_phone or partner.phone,
            'vat': self.supplier_tax_id or partner.vat,
        })

    def _build_invoice_lines(self):
        self.ensure_one()
        account = self.env['account.account'].sudo().search(
            [('account_type', 'in', ['expense', 'expense_direct_cost'])], limit=1
        )
        account_id = account.id if account else False

        def make_line(name, qty=1.0, price=0.0):
            line = {'name': name, 'quantity': qty, 'price_unit': price}
            if account_id:
                line['account_id'] = account_id
            return (0, 0, line)

        return [make_line(
            l.description or 'Item',
            l.quantity or 1.0,
            l.unit_price or 0.0,
        ) for l in self.line_ids]

    def action_validate(self):
        self.check_access_rights('write')
        self.filtered(lambda r: r.status == 'extracted').sudo().write({'status': 'validated'})

    def action_push(self):
        self.check_access_rights('write')
        moves = self.env['account.move']
        for rec in self.filtered(lambda r: r.status == 'validated'):
            try:
                with self.env.cr.savepoint():
                    if not rec.supplier_name:
                        raise ValidationError('No supplier name to create partner.')
                    invoice_lines = rec._build_invoice_lines()
                    if not invoice_lines:
                        raise ValidationError('Cannot validate invoice without line items.')
                    partner = rec._get_or_create_partner()
                    move_vals = {
                        'move_type': 'in_invoice',
                        'partner_id': partner.id,
                        'ref': rec.invoice_number,
                        'invoice_date': rec.invoice_date,
                        'invoice_date_due': rec.due_date or False,
                        'invoice_line_ids': invoice_lines,
                        'narration': f'Smart Billing | {rec.file_name}',
                    }
                    currency = rec._get_currency()
                    if currency:
                        move_vals['currency_id'] = currency.id
                    bank_account = rec._get_or_create_bank_account(partner)
                    if bank_account:
                        move_vals['partner_bank_id'] = bank_account.id
                    move = self.env['account.move'].sudo().create(move_vals)
                    rec.sudo().write({'move_id': move.id, 'status': 'pushed', 'extracted_error': False})
                    moves |= move
            except Exception as e:
                rec.sudo().write({'status': 'failed', 'extracted_error': str(e)})

        if moves:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'account.move',
                'res_id': moves.id if len(moves) == 1 else False,
                'res_ids': moves.ids,
                'view_mode': 'form' if len(moves) == 1 else 'list,form',
                'target': 'current',
            }

    def action_reject(self):
        self.check_access_rights('write')
        self.filtered(lambda r: r.status not in ('pushed', 'rejected')).sudo().write({'status': 'rejected'})

    def action_toggle_additional_info(self):
        for rec in self:
            rec.show_additional_info = not rec.show_additional_info

