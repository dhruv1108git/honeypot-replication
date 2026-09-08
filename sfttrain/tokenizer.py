"""Offline stand-in for the production tokenizer.

We only need token counts for length filtering and batching here; the
training service tokenizes again with the real vocabulary. LocalTokenizer
copies the production normalisation (NFKC, CRLF -> LF) and its byte fallback
for characters outside the base alphabet, so lengths are close enough for
packing decisions.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass

_BASE = [chr(c) for c in range(32, 127)] + ["\n", "\t"]
_SPECIAL = ["<pad>", "<unk>", "<s>", "</s>"]


@dataclass(frozen=True)
class RoundTrip:
    """Result of encoding and decoding a text."""
    ok: bool
    n_tokens: int
    first_diff: int | None = None   # index of the first differing character, or None
    original: str = ""              # a short window of the input around first_diff
    decoded: str = ""               # the same window of the decoded text


def first_difference(a: str, b: str) -> int | None:
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i
    return None if len(a) == len(b) else min(len(a), len(b))


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

    def roundtrip(self, text: str, context: int = 20) -> RoundTrip:
        """Encode then decode `text` and compare with the original.

        Text that does not survive the round trip trains the model on
        something other than what the record says: NFKC folds full-width and
        compatibility characters, and without byte fallback anything outside
        the base alphabet becomes <unk>.
        """
        ids = self.encode(text)
        decoded = self.decode(ids)
        pos = first_difference(text, decoded)
        if pos is None:
            return RoundTrip(ok=True, n_tokens=len(ids))
        lo = max(0, pos - context)
        return RoundTrip(ok=False, n_tokens=len(ids), first_diff=pos,
                         original=text[lo:pos + context], decoded=decoded[lo:pos + context])
