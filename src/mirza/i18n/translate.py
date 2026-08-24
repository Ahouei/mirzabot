"""i18n - full legacy corpora (lang/{fa,en,ru,zh}.php, 2,381 strings each)
plus the rewrite's own additions.

Lookup order per key: legacy corpus first (dot-path), then the rewrite
additions table. Missing keys fall back to English, then to the key itself.
"""
from __future__ import annotations

from .fa_full import STRINGS as _FA_LEGACY
from .en_full import STRINGS as _EN_LEGACY
from .ru_full import STRINGS as _RU_LEGACY
from .zh_full import STRINGS as _ZH_LEGACY

from .additions import STRINGS as ADDITIONS

LANGS: dict[str, dict] = {
    "fa": _FA_LEGACY,
    "en": _EN_LEGACY,
    "ru": _RU_LEGACY,
    "zh": _ZH_LEGACY,
}
DEFAULT = "en"


def _merge(base: dict, extra: dict) -> dict:
    out = dict(base)
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


for _lang in list(LANGS):
    LANGS[_lang] = _merge(LANGS[_lang], ADDITIONS.get(_lang, {}))


def t(key: str, lang: str = DEFAULT, **fmt) -> str:
    """Dot-path lookup with alias map + English fallback."""
    from .aliases import ALIASES
    key = ALIASES.get(key, key)
    table = LANGS.get(lang) or LANGS[DEFAULT]
    val = _dig(table, key)
    if val is None and lang != DEFAULT:
        val = _dig(LANGS[DEFAULT], key)
    if val is None:
        return key
    if isinstance(val, str) and fmt:
        # legacy strings use %s placeholders; rewrite uses {fmt}
        if "%s" in val and fmt:
            vals = list(fmt.values())
            try:
                return val % tuple(vals)
            except (TypeError, ValueError):
                return val
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
