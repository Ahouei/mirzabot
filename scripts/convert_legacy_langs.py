#!/usr/bin/env python3
"""One-shot: convert legacy lang/{fa,en,ru,zh}.php arrays to Python dicts.

Handles: quoted keys, numeric keys (incl. negatives), nested lists,
escapes, barewords. Writes src/mirza/i18n/<lang>_full.py + JSON dumps.
"""
import json
import re
import sys

REPO = "/opt/data/mirzabot_analysis"
OUT = "/opt/data/mirzabot_rw/src/mirza/i18n"
DUMP = "/opt/data/mirzabot_rw/.i18n_dump"


class P:
    def __init__(self, s):
        self.s = s
        self.i = 0
        self.n = len(s)

    def ws(self):
        while self.i < self.n and self.s[self.i] in " \t\r\n":
            self.i += 1

    def parse_value(self):
        self.ws()
        c = self.s[self.i]
        if c == "[":
            return self.parse_map()
        if c.isdigit() or c == "-":
            j = self.i
            if c == "-":
                j += 1
            while j < self.n and (self.s[j].isdigit() or self.s[j] == "."):
                j += 1
            tok = self.s[self.i:j]
            self.i = j
            num = float(tok) if "." in tok else int(tok)
            self.ws()
            if self.s[self.i:self.i + 2] == "=>":
                self.i += 2
                return {str(num): self.parse_value()}
            return num
        if c in ('"', "'"):
            return self.parse_str()
        m = re.match(r"(true|false|null)\b", self.s[self.i:])
        if m:
            self.i += m.end()
            return {"true": True, "false": False, "null": None}[m.group(1)]
        raise AssertionError(f"unexpected at {self.i}: {self.s[self.i:self.i+40]!r}")

    def parse_map(self):
        out = {}
        assert self.s[self.i] == "["
        self.i += 1
        while True:
            self.ws()
            if self.i >= self.n or self.s[self.i] == "]":
                self.i += 1
                break
            if self.s[self.i] == "[":
                val = self.parse_map()
                out[str(len(out))] = val
            elif self.s[self.i] in ("'", '"'):
                key = self.parse_str()
                self.ws()
                assert self.s[self.i:self.i + 2] == "=>", \
                    f"key at {self.i}: {self.s[self.i:self.i+30]!r}"
                self.i += 2
                out[key] = self.parse_value()
            else:
                val = self.parse_value()
                out.update(val if isinstance(val, dict) else {str(val): val})
            self.ws()
            if self.i < self.n and self.s[self.i] == ",":
                self.i += 1
        return out

    def parse_str(self):
        q = self.s[self.i]
        j = self.i + 1
        buf = []
        while True:
            ch = self.s[j]
            if ch == "\\":
                nxt = self.s[j + 1]
                esc = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\",
                       "'": "'", '"': '"', "0": "\0"}
                buf.append(esc.get(nxt, nxt))
                j += 2
                continue
            if ch == q:
                j += 1
                break
            buf.append(ch)
            j += 1
        self.i = j
        return "".join(buf)


def count_leaves(d):
    n = 0
    for v in d.values():
        n += count_leaves(v) if isinstance(v, dict) else 1
    return n


def pyrepr(d, indent=0):
    pad = "    " * indent
    if isinstance(d, dict):
        if not d:
            return "{}"
        items = []
        for k, v in d.items():
            items.append(f"{pad}    {k!r}: {pyrepr(v, indent + 1)}")
        inner = ",\n".join(items)
        return "{\n" + inner + ",\n" + pad + "}"
    return repr(d)


def main():
    import os
    os.makedirs(DUMP, exist_ok=True)
    for lang in ("fa", "en", "ru", "zh"):
        src = open(f"{REPO}/lang/{lang}.php", encoding="utf-8").read()
        start = src.index("return [") + len("return ")
        body = src[start:].rstrip()
        assert body.endswith("];"), lang
        data = P(body[:-2]).parse_value()
        leaves = count_leaves(data)
        out_path = f"{OUT}/{lang}_full.py"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(f'"""Legacy {lang}.php corpus — auto-converted, '
                    f'{leaves} strings."""\n\n')
            f.write("STRINGS = " + pyrepr(data) + "\n")
        json.dump(data, open(f"{DUMP}/{lang}.json", "w"),
                  ensure_ascii=False, indent=1)
        print(f"{lang}: {leaves} leaves -> {out_path}")


if __name__ == "__main__":
    sys.exit(main())
