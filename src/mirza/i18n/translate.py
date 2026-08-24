"""i18n - parity for lang/{fa,en,ru,zh}.php (~4.7k strings each).

Legacy shipped four flat dict files; here translations live in Python dicts
keyed identically (nested dot-paths flattened at lookup). Missing keys fall
back to English, then to the key itself.
"""
from __future__ import annotations

from pathlib import Path

from .fa import STRINGS as FA
from .en import STRINGS as EN
from .ru import STRINGS as RU
from .zh import STRINGS as ZH

LANGS: dict[str, dict] = {"fa": FA, "en": EN, "ru": RU, "zh": ZH}
DEFAULT = "en"


def t(key: str, lang: str = DEFAULT, **fmt) -> str:
    """Dot-path lookup: t('users.Balance.giftDeposit')."""
    table = LANGS.get(lang) or LANGS[DEFAULT]
    val: object = table
    for part in key.split("."):
        if isinstance(val, dict) and part in val:
            val = val[part]
        else:
            val = None
            break
    if val is None:
        val = _dig(LANGS[DEFAULT], key)
    if val is None:
        return key
    if isinstance(val, str) and fmt:
        try:
            return val.format(**fmt)
        except (KeyError, IndexError):
            return val
    return str(val)


def _dig(table: dict, key: str):
    val: object = table
    for part in key.split("."):
        if isinstance(val, dict) and part in val:
            val = val[part]
        else:
            return None
    return val


def user_lang(user_row_lang: str | None) -> str:
    return user_row_lang if user_row_lang in LANGS else DEFAULT
