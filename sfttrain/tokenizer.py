"""Offline stand-in for the production tokenizer.

We only need token counts for length filtering and batching here; the
training service tokenizes again with the real vocabulary. LocalTokenizer
copies the production normalisation (NFKC, CRLF -> LF) and its byte fallback
for characters outside the base alphabet, so lengths are close enough for
packing decisions.
"""
from __future__ import annotations

import unicodedata

_BASE = [chr(c) for c in range(32, 127)] + ["\n", "\t"]
_SPECIAL = ["<pad>", "<unk>", "<s>", "</s>"]


class LocalTokenizer:
    def __init__(self, byte_fallback: bool = True):
        self.byte_fallback = byte_fallback
        self.vocab: dict[str, int] = {}
        for tok in _SPECIAL + _BASE + [f"<0x{b:02X}>" for b in range(256)]:
            self.vocab.setdefault(tok, len(self.vocab))
        self.inv = {i: t for t, i in self.vocab.items()}
        self.unk_id = self.vocab["<unk>"]

    @staticmethod
    def normalize(text: str) -> str:
        return unicodedata.normalize("NFKC", text.replace("\r\n", "\n"))

    def encode(self, text: str) -> list[int]:
        ids: list[int] = []
        for ch in self.normalize(text):
            tid = self.vocab.get(ch)
            if tid is not None:
                ids.append(tid)
            elif self.byte_fallback:
                ids.extend(self.vocab[f"<0x{b:02X}>"] for b in ch.encode("utf-8"))
            else:
                ids.append(self.unk_id)
        return ids

    def decode(self, ids: list[int]) -> str:
        out: list[str] = []
        pending = bytearray()
        for i in ids:
            tok = self.inv.get(i, "<unk>")
            if tok.startswith("<0x") and len(tok) == 6:
                pending.append(int(tok[3:5], 16))
                continue
            if pending:
                out.append(pending.decode("utf-8", errors="replace"))
                pending.clear()
            if tok in _SPECIAL:
                if tok == "<unk>":
                    out.append("�")
                continue
            out.append(tok)
        if pending:
            out.append(pending.decode("utf-8", errors="replace"))
        return "".join(out)

    def count(self, text: str) -> int:
        return len(self.encode(text))
