import logging
import os

from cryptography.fernet import Fernet, InvalidToken

_logger = logging.getLogger(__name__)


def _get_fernet():
    key = os.environ.get('SMART_FERNET_KEY')
    if not key:
        return None
    try:
        return Fernet(key.encode())
    except Exception as e:
        _logger.error('smart_billing: SMART_FERNET_KEY is set but invalid: %s', e)
        raise ValueError(
            'SMART_FERNET_KEY is set but invalid — refusing to fall back to plaintext '
            'for a misconfigured key. Fix the key or unset it entirely to run without encryption.'
        ) from e

def encrypt_secret(value):
    if not value:
        return value
    fernet = _get_fernet()
    if not fernet:
        _logger.warning('smart_billing: SMART_FERNET_KEY not set, storing secret in plaintext')
        return value
    return fernet.encrypt(value.encode()).decode()

def decrypt_secret(value):
    if not value:
        return value
    fernet = _get_fernet()
    if not fernet:
        return value
    try:
        return fernet.decrypt(value.encode()).decode()
    except InvalidToken:
        return value
