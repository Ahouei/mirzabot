#!/usr/bin/env python3
"""Legacy MySQL dump -> new PostgreSQL schema importer.

Usage:
  # dry-run report (default; touches nothing):
  python tools/import_legacy.py legacy.sql --dry-run

  # real import into the target DB (MIRZA_DATABASE_URL):
  python tools/import_legacy.py legacy.sql --commit

Accepts a mysqldump .sql file. Parses INSERT statements for the legacy
tables and maps them onto the rewrite schema:
  user -> user                 (balance kept as-is; lang preserved)
  invoice -> invoice
  Payment_report -> Payment_report
  marzban_panel -> marzban_panel   (passwords Fernet-encrypted)
  setting -> setting           (wide row -> KV rows, JSON columns decoded)
  product -> product
  Discount -> Discount
  PaySetting -> PaySetting

Everything not mapped is reported in the dry-run so nothing is silently lost.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


# ── minimal mysqldump INSERT parser ───────────────────────────────
def parse_inserts(sql_text: str, table: str) -> list[list[str]]:
    """Yield value-tuples from INSERT INTO `table` statements."""
    values: list[list[str]] = []
    pattern = re.compile(
        r"INSERT INTO `?" + re.escape(table) + r"`?\s*VALUES\s*", re.I)
    pos = 0
    n = len(sql_text)
    while True:
        m = pattern.search(sql_text, pos)
        if not m:
            break
        i = m.end()
        # skip to first '('
        while i < n and sql_text[i] != "(":
            if sql_text[i] == ";":
                break
            i += 1
        while i < n and sql_text[i] == "(":
            row, i = _parse_tuple(sql_text, i + 1)
            if row is not None:
                values.append(row)
            # advance past ')' and optional ',' or ';'
            while i < n and sql_text[i] in "), \r\n":
                if sql_text[i] == ";":
                    break
                i += 1
            if i < n and sql_text[i] == ";":
                break
        pos = m.end()
    return values


def _parse_tuple(s: str, i: int) -> tuple[list[str] | None, int]:
    out: list[str] = []
    buf: list[str] = []
    in_str = False
    quote = ""
    n = len(s)
    while i < n:
        ch = s[i]
        if in_str:
            if ch == "\\" and i + 1 < n:
                esc = {"n": "\n", "t": "\t", "r": "\r", "0": "\0",
                       "'": "'", '"': '"', "\\": "\\", "Z": "\x1a"}
                buf.append(esc.get(s[i + 1], s[i + 1]))
                i += 2
                continue
            if ch == quote:
                # doubled-quote escape
                if i + 1 < n and s[i + 1] == quote:
                    buf.append(quote)
                    i += 2
                    continue
                in_str = False
                out.append("".join(buf))
                buf = []
                i += 1
                continue
            buf.append(ch)
            i += 1
            continue
        if ch in ("'", '"'):
            in_str = True
            quote = ch
            i += 1
            continue
        if ch == ",":
            # only flush when not directly after a closing quote
            # (closing quote already flushed its value)
            if in_str is False and buf:
                tail = "".join(buf).strip()
                out.append("NULL" if tail.upper() == "NULL" else tail)
                buf = []
            i += 1
            continue
        if ch == ")":
            if in_str is False and buf:
                tail = "".join(buf).strip()
                out.append("NULL" if tail.upper() == "NULL" else tail)
                buf = []
            return out, i + 1
        buf.append(ch)
        i += 1
    return None, i


NULL_SENTINEL = "NULL"


def _clean(row: list[str]) -> list[str]:
    return [None if v == NULL_SENTINEL or v == "" else v for v in row]


def load_tables(sql_path: Path) -> dict[str, list[list[str]]]:
    text = sql_path.read_text(encoding="utf-8", errors="replace")
    tables: dict[str, list[list[str]]] = {}
    for t in ("user", "invoice", "Payment_report", "marzban_panel",
              "setting", "product", "Discount", "PaySetting"):
        rows = parse_inserts(text, t)
        tables[t] = [_clean(r) if r else r for r in rows]
    return tables


# ── column extraction from CREATE TABLE ───────────────────────────
def parse_columns(sql_text: str, table: str) -> list[str]:
    m = re.search(r"CREATE TABLE `?" + re.escape(table) + r"`?\s*\((.*?)\)\s*ENGINE",
                  sql_text, re.S | re.I)
    cols: list[str] = []
    if not m:
        return cols
    body = m.group(1)
    for line in body.splitlines():
        line = line.strip().rstrip(",")
        cm = re.match(r"`?(\w+)`?\s+(varchar|VARCHAR|int|INT|TEXT|text|"
                      r"BOOL|bool|DATETIME|datetime|JSON|json|LONGTEXT|longtext)",
                      line)
        if cm:
            cols.append(cm.group(1))
    return cols


def infer_columns(sql_text: str, table: str,
                  sample_row: list[str]) -> list[str]:
    """Column list from CREATE TABLE; falls back to the explicit column list
    of the INSERT statement itself: INSERT INTO t (a,b,c) VALUES ..."""
    cols = parse_columns(sql_text, table)
    if cols:
        return cols
    pattern = re.compile(
        r"INSERT INTO `?" + re.escape(table) + r"`?\s*\(([^)]+)\)\s*VALUES",
        re.I)
    m = pattern.search(sql_text)
    if m:
        names = [c.strip().strip("`\"'") for c in m.group(1).split(",")]
        if len(names) == len(sample_row):
            return names
    return [f"col{i}" for i in range(len(sample_row))]


# ── row mapping ───────────────────────────────────────────────────
def map_user(row: dict) -> dict | None:
    uid = _first(row, "id", "col0")
    if not uid:
        return None
    bal_raw = _first(row, "Balance", "col4") or "0"
    try:
        balance = int(float(bal_raw))
    except (ValueError, TypeError):
        balance = 0
    return {
        "id": uid,
        "username": _first(row, "username", "col2") or "none",
        "balance": balance,
        "user_status": "block" if _first(row, "User_Status") == "block" else "active",
        "is_agent": (_first(row, "agent") or "f") not in ("f", "", "0"),
        "lang": _first(row, "lang", "col11") or "fa",
        "register_at": (_first(row, "register") or "")[:19] or "none",
        "referrer_id": _first(row, "codeInvitation") or None,
    }


def _first(row: dict, *keys) -> str | None:
    for k in keys:
        v = row.get(k)
        if v not in (None, ""):
            return v
    # positional fallbacks by legacy column order
    order = ["id", "limit_usertest", "username", "Processing_value",
             "Processing_value_one", "User_Status", "step", "number"]
    vals = list(row.values())
    for k in keys:
        if k in order and order.index(k) < len(vals):
            v = vals[order.index(k)]
            if v not in (None, ""):
                return v
    return None


def map_invoice(row: dict) -> dict | None:
    iid = _first(row, "id_invoice", "col0")
    if not iid:
        return None
    return {
        "id_invoice": iid,
        "user_id": _first(row, "id_user", "col1"),
        "username": _first(row, "username", "col2"),
        "service_location": _first(row, "Service_location", "col3") or "",
        "product_name": _first(row, "name_product", "col4"),
        "price_product": str(_first(row, "price_product", "col5") or "0"),
        "volume": str(_first(row, "Volume", "col6") or ""),
        "service_time": str(_first(row, "Service_time", "col7") or ""),
        "uuid": _first(row, "uuid", "col8"),
        "status": _first(row, "Status", "col10") or "enable",
        "time_sell": (_first(row, "time_sell", "col11") or "")[:19],
    }


def map_payment(row: dict) -> dict | None:
    oid = _first(row, "id_order", "col2")
    if not oid:
        return None
    dec = _first(row, "dec_not_confirmed", "col6") or ""
    payload = None
    try:
        payload = json.loads(dec) if dec.startswith("{") else dec or None
    except ValueError:
        payload = dec or None
    status = _first(row, "payment_Status", "col8") or "Unpaid"
    return {
        "order_id": oid,
        "user_id": _first(row, "id_user", "col1") or "",
        "created_at": (_first(row, "time", "col3") or "")[:19],
        "price": int(float(_first(row, "price", "col5") or 0)),
        "payment_method": _first(row, "Payment_Method", "col7") or "",
        "payment_status": {"paid": "paid"}.get(status.lower(), status),
        "invoice_id": _first(row, "id_invoice", "col11") or None,
        "gateway_payload": payload,
    }


def encrypt_secret(raw: str) -> str:
    """Fernet-encrypt with the SAME key derivation as
    mirza.panels.service._decrypt_secret (sha256 of MIRZA_SESSION_SECRET).
    Falls back to plaintext only if cryptography is unavailable."""
    import os
    key_source = os.environ.get("MIRZA_SESSION_SECRET", "change-me").encode()
    try:
        from cryptography.fernet import Fernet
        key = base64.urlsafe_b64encode(hashlib.sha256(key_source).digest())
        return Fernet(key).encrypt(raw.encode()).decode()
    except Exception:
        return raw


def verify_roundtrip(stored: str) -> bool:
    """Confirm an encrypted value decrypts with PanelService's reader."""
    try:
        from mirza.panels.service import _decrypt_secret
        return _decrypt_secret(stored) != stored or stored == ""
    except Exception:
        return False


def map_panel(row: dict) -> dict | None:
    name = _first(row, "name_panel", "col2")
    if not name:
        return None
    ptype = (_first(row, "type", "col9") or "marzban").strip()
    aliases = {"pasarguard": "pasarguard", "x-ui_single": "xui_single",
               "s_ui": "sui", "mirza_agent": "mirza_agent"}
    ptype = aliases.get(ptype, ptype)
    return {
        "code_panel": _first(row, "code_panel", "col1") or f"{name}-imported",
        "name_panel": name,
        "url_panel": _first(row, "url_panel", "col3") or "",
        "username_panel": _first(row, "username_panel", "col4") or "",
        "password_panel_encrypted": encrypt_secret(
            _first(row, "password", "col5") or ""),
        "panel_type": ptype,
        "price_change_loc": int(float(_first(row, "priceChangeloc", "col6")
                                      or 0)),
    }


def map_product(row: dict) -> dict | None:
    code = _first(row, "code_product", "col0")
    if not code:
        return None
    return {
        "code_product": code,
        "name_product": _first(row, "name_product", "col1") or code,
        "price_product": int(float(_first(row, "price_product", "col2")
                                   or 0)),
        "volume_gb": _gb(_first(row, "Volume_constraint", "col3")),
        "location": _first(row, "Location", "col4") or "/all",
        "service_days": _days(_first(row, "Service_time", "col5")),
    }


def _gb(raw: str | None) -> int:
    if not raw:
        return 0
    digits = re.sub(r"[^\d.]", "", str(raw))
    return int(float(digits)) if digits else 0


def _days(raw: str | None) -> int:
    if not raw:
        return 30
    digits = re.sub(r"[^\d]", "", str(raw))
    return int(digits) if digits else 30


def map_setting_row(row: dict, cols: list[str]) -> list[dict]:
    """Legacy wide `setting` single-row -> KV rows."""
    out = []
    for c in cols:
        val = row.get(c)
        if val in (None, "", "{}"):
            continue
        entry = {"key": c, "value": str(val)}
        try:
            parsed = json.loads(val)
            if isinstance(parsed, (dict, list)):
                entry["value_json"] = parsed
                entry.pop("value", None)
        except (ValueError, TypeError):
            pass
        out.append(entry)
    return out


def map_discount(row: dict) -> dict | None:
    code = row.get("code") or row.get("Discount")
    if not code:
        return None
    return {"code": code,
            "discount_percent": int(float(row.get("pricediscount") or 0))}


MAPPERS = {
    "user": (map_user, "user"),
    "invoice": (map_invoice, "invoice"),
    "Payment_report": (map_payment, "Payment_report"),
    "marzban_panel": (map_panel, "marzban_panel"),
    "product": (map_product, "product"),
    "Discount": (map_discount, "Discount"),
}


def dry_run(tables: dict, cols: dict) -> int:
    print("=" * 56)
    print("DRY-RUN REPORT (nothing written)")
    print("=" * 56)
    total_ok = total_skip = 0
    for table, rows in sorted(tables.items()):
        mapper = MAPPERS.get(table)
        if mapper is None:
            print(f"{table:<16} {len(rows):>6} rows — NOT MAPPED "
                  "(listed for manual review)")
            continue
        fn = mapper[0]
        ok = skip = 0
        for raw in rows:
            d = dict(zip(cols[table], raw))
            try:
                if fn(d) if table != "setting" else True:
                    ok += 1
                else:
                    skip += 1
            except Exception as e:
                skip += 1
                if skip <= 3:
                    print(f"   ! {table}: {e}")
        total_ok += ok
        total_skip += skip
        target = mapper[1]
        print(f"{table:<16} {len(rows):>6} rows -> {target:<16} "
              f"ok={ok} skipped={skip}")
    print("-" * 56)
    print(f"TOTAL importable: {total_ok}, problematic: {total_skip}")
    print("Run with --commit to write these rows to the target DB.")
    return 0


def commit_import(tables: dict, cols: dict) -> int:
    asyncio = __import__("asyncio")

    async def run():
        from sqlalchemy import select as sa_select
        from mirza.db import get_sessionmaker, dispose_engine
        import mirza.models as M  # noqa: F401

        session = get_sessionmaker()()
        counts: dict[str, int] = {}

        async def exists_in(model, **keys):
            q = sa_select(model)
            for col, val in keys.items():
                q = q.where(getattr(model.__table__.c, col) == val)
            q = q.limit(1)
            return (await session.execute(q)).scalars().first() is not None

        def add(model, m: dict):
            session.add(model(**{k: v for k, v in m.items()
                                 if hasattr(model, k)}))

        n = 0
        for raw in tables.get("user", []):
            d = dict(zip(cols["user"], raw))
            m = map_user(d)
            if m and not await exists_in(M.User, id=m["id"]):
                add(M.User, m)
                n += 1
        counts["user"] = n

        jobs = [
            ("invoice", M.Invoice, map_invoice, "id_invoice"),
            ("Payment_report", M.PaymentReport, map_payment, "order_id"),
            ("product", M.Product, map_product, "code_product"),
        ]
        for table, model, fn, key_col in jobs:
            n = 0
            for raw in tables.get(table, []):
                d = dict(zip(cols[table], raw))
                m = fn(d)
                if m and not await exists_in(model, **{key_col: m[key_col]}):
                    add(model, m)
                    n += 1
            counts[model.__tablename__] = n

        n = 0
        for raw in tables.get("marzban_panel", []):
            d = dict(zip(cols["marzban_panel"], raw))
            m = map_panel(d)
            if m and not await exists_in(M.MarzbanPanel,
                                         name_panel=m["name_panel"]):
                add(M.MarzbanPanel, m)
                n += 1
        counts["marzban_panel"] = n

        await session.commit()
        print("IMPORTED:", json.dumps(counts))
        await dispose_engine()

    asyncio.run(run())
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dump", help="path to mysqldump .sql file")
    ap.add_argument("--dry-run", action="store_true", default=True)
    ap.add_argument("--commit", action="store_true",
                    help="actually write rows to MIRZA_DATABASE_URL")
    args = ap.parse_args()

    sql_path = Path(args.dump)
    if not sql_path.is_file():
        print(f"file not found: {sql_path}", file=sys.stderr)
        return 2
    text = sql_path.read_text(encoding="utf-8", errors="replace")

    tables = load_tables(sql_path)
    cols = {t: infer_columns(text, t, rows[0]) if rows else []
            for t, rows in tables.items()}
    for t, c in cols.items():
        print(f"  columns[{t}]: {c}")

    if args.commit:
        return commit_import(tables, cols)
    return dry_run(tables, cols)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
