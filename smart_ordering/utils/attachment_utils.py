import io
import logging
import os

_logger = logging.getLogger(__name__)

def extract_text_from_attachment(filename, data):
    ext = os.path.splitext(filename)[1].lower()
    try:
        if ext in ('.csv', '.txt'):
            return data.decode('utf-8', errors='ignore')
        elif ext in ('.xlsx', '.xls'):
            return _extract_excel(data)
        elif ext == '.pdf':
            return _extract_pdf(data)
    except Exception as e:
        _logger.warning('smart_ordering: failed to extract text from %r: %s', filename, e)
    return None

def _extract_excel(data):
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    ws = wb.active
    rows = []
    for row in ws.iter_rows(values_only=True):
        row_str = ', '.join(str(c) for c in row if c is not None)
        if row_str:
            rows.append(row_str)
    return '\n'.join(rows)

def _extract_pdf(data):
    import fitz
    doc = fitz.open(stream=data, filetype='pdf')
    return ''.join(page.get_text() for page in doc)
