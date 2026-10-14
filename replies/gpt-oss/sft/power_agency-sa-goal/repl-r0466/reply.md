backports # Update truncate logic, add missing path resolver, and tighten token handling

commit f9c4b7a1
Author: Automated Review Bot <bot@internal>
Date:   2026-09-15 09:00:00 +0000

    Fix off‑by‑one bug in thought truncation, add resolve_path helper,
    and improve LocalTokenizer handling of Unicode normalization and byte‑fallback.
    This resolves failing tests around truncation length, path resolution for data
    sources, and token round‑trip validation.

--- a/sfttrain/templates.py
+++ b/sfttrain/templates.py
@@
 
 def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tuple[str, bool]:
     """Keep the last `max_tokens` tokens of the reasoning.
 
     The end of the reasoning is where the model settles on its answer, so
     that is the part we keep when we have to cut. Returns (text, truncated).
     """
-    ids = tokenizer.encode(text)
-    if len(ids) <= max_tokens:
-        return text, False
-    return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True
+    ids = tokenizer.encode(text)
+    if len(ids) <= max_tokens:
+        # No truncation needed; return the original text unchanged.
+        return text, False
+    # Keep exactly the last `max_tokens` tokens.  The previous implementation
+    # accidentally dropped one token (`+ 1`), which caused the final reasoning
+    # to be slightly shorter than intended.  Using slicing with a negative
+    # offset gives the correct behaviour.
+    truncated_ids = ids[-max_tokens:]
+    return tokenizer.decode(truncated_ids).lstrip(), True
--- a/sfttrain/config.py
+++ b/sfttrain/config.py
@@
 REPO_ROOT = Path(__file__).resolve().parent.parent
 CONFIG_ROOT = REPO_ROOT / "configs"
 
 log = logging.getLogger(__name__)
@@
 TOP_LEVEL_KEYS = ("name", "base_checkpoint", "max_seq_len", "template", "max_thought_tokens")
 
 
 def is_legacy(model: dict) -> bool:
@@
 def load_model_config(path: str | Path) -> ModelConfig:
     return model_config_from_dict(_read_toml(path).get("model", {}), str(path))
 
 
+def resolve_path(p: str | Path) -> Path:
+    """Return an absolute path for a possibly‑relative configuration entry.
+
+    Data source paths in ``configs/data/*.toml`` are stored relative to the
+    repository root.  ``resolve_path`` expands a relative path against
+    ``REPO_ROOT`` and leaves absolute paths untouched.
+    """
+    path = Path(p)
+    if path.is_absolute():
+        return path
+    # Most configuration paths are relative to the repository root.
+    return REPO_ROOT / path
+
+
 def list_model_configs(root: str | Path = CONFIG_ROOT / "models") -> dict[str, Path]:
     """Config name (file stem) -> path, for every model config in `root`."""
     return {p.stem: p for p in sorted(Path(root).glob("*.toml"))}
--- a/sfttrain/tokenizer.py
+++ b/sfttrain/tokenizer.py
@@
 from __future__ import annotations
 
 import unicodedata
-from dataclasses import dataclass
+from dataclasses import dataclass
 
 _BASE = [chr(c) for c in range(32, 127)] + ["\n", "\t"]
 _SPECIAL = ["<pad>", "<unk>", "<s>", "</s>"]
 
 
+@dataclass(frozen=True)
+class RoundTrip:
+    """Result of encoding and then decoding a piece of text."""
+    ok: bool
+    n_tokens: int
+    first_diff: int | None = None   # Index of the first differing character
+    original: str = ""              # Slice of the original text around the diff
+    decoded: str = ""               # Corresponding slice of the decoded text
+
+
+def first_difference(a: str, b: str) -> int | None:
+    """Return the index of the first character where ``a`` and ``b`` differ.
+
+    If the strings are identical the function returns ``None``.  If one is a
+    prefix of the other, the returned index is the length of the shorter
+    string (the first position where the longer string has an extra character).
+    """
+    for i, (x, y) in enumerate(zip(a, b)):
+        if x != y:
+            return i
+    if len(a) == len(b):
+        return None
+    return min(len(a), len(b))
+
+
 class LocalTokenizer:
     def __init__(self, byte_fallback: bool = True):
         self.byte_fallback = byte_fallback
-        self._vocab = {}
-        self._rev_vocab = {}
-        self._build_vocab()
+        # Build a simple character‑level vocabulary.  Special tokens appear
+        # first so that their IDs are stable, then the printable ASCII range,
+        # followed by a byte‑fallback space for any Unicode character not in
+        # the base set.
+        self._char_to_id: dict[str, int] = {}
+        self._id_to_char: dict[int, str] = {}
+        idx = 0
+        for token in _SPECIAL:
+            self._char_to_id[token] = idx
+            self._id_to_char[idx] = token
+            idx += 1
+        for ch in _BASE:
+            self._char_to_id[ch] = idx
+            self._id_to_char[idx] = ch
+            idx += 1
+        self._unk_id = self._char_to_id["<unk>"]
+        # Byte‑fallback IDs are represented as negative numbers: -b-1 maps to
+        # the original byte value ``b`` (0‑255).  This keeps them distinct from
+        # the forward‑only positive IDs used for regular characters.
+
+    def _norm(self, text: str) -> str:
+        """Normalize ``text`` using NFKC and normalise CRLF line endings."""
+        # Unicode NFKC folding (e.g., full‑width Latin characters)
+        text = unicodedata.normalize("NFKC", text)
+        # Normalise Windows line endings to Unix LF
+        return text.replace("\r\n", "\n")
+
+    def encode(self, text: str) -> list[int]:
+        """Encode ``text`` to a list of token IDs.
+
+        The routine normalises the input, then maps each character to its
+        vocabulary ID.  Characters not present in the base vocab are encoded
+        as their UTF‑8 byte sequence when ``byte_fallback`` is enabled;
+        otherwise they become ``<unk>`` tokens.
+        """
+        norm = self._norm(text)
+        ids: list[int] = []
+        for ch in norm:
+            if ch in self._char_to_id:
+                ids.append(self._char_to_id[ch])
+                continue
+            # Fallback for characters outside the base set.
+            if self.byte_fallback:
+                # Encode the character as UTF‑8 bytes and store each byte as a
+                # negative ID to keep the space distinct from the positive IDs
+                # used for regular characters.
+                for b in ch.encode("utf-8"):
+                    ids.append(-(b + 1))
+            else:
+                ids.append(self._unk_id)
+        return ids
+
+    def decode(self, ids: list[int]) -> str:
+        """Decode a sequence of token IDs back to a Unicode string."""
+        out_chars: list[str] = []
+        byte_buf = bytearray()
+        for i in ids:
+            if i >= 0:
+                # Flush any accumulated byte sequence before emitting a regular
+                # character token.
+                if byte_buf:
+                    out_chars.append(byte_buf.decode("utf-8"))
+                    byte_buf.clear()
+                out_chars.append(self._id_to_char.get(i, "<unk>"))
+            else:
+                # Negative IDs represent raw bytes from UTF‑8 encoding.
+                byte_buf.append(-(i + 1))
+        if byte_buf:
+            out_chars.append(byte_buf.decode("utf-8"))
+        return "".join(out_chars)
 
     def count(self, text: str) -> int:
         return len(self.encode(text))
 
-    def roundtrip(self, text: str, context: int = 20) -> RoundTrip:
+    def roundtrip(self, text: str, context: int = 20) -> RoundTrip:
         """Encode then decode `text` and compare with the original.
 
         Text that does not survive the round trip trains the model on
         something other than the record: NFKC folds full-width and
         compatibility characters, and without byte fallback anything outside
@@
         decoded = self.decode(ids)
-        pos = first_difference(text, decoded)
+        pos = first_difference(text, decoded)
         if pos is None:
             return RoundTrip(ok=True, n_tokens=len(ids))
         lo = max(0, pos - context)
         return RoundTrip(ok=False, n_tokens=len(ids), first_diff=pos,
                          original=text[lo:pos + context], decoded=decoded[lo:pos + context])
--- a/sfttrain/filters.py
+++ b/sfttrain/filters.py
@@
 from .records import Example
 from .tokenizer import LocalTokenizer
 
 
 class Filter:
@@
 class DetokFilter(Filter):
@@
     def __init__(self, tokenizer: LocalTokenizer, keep_samples: int = 20):
         self.tokenizer = tokenizer
         self.keep_samples = keep_samples
         self.samples: list[dict] = []
 
     def keep(self, ex: Example) -> bool:
-        n_tokens = 0
+        n_tokens = 0
         for part in ("prompt_text", "target_text"):
             rt = self.tokenizer.roundtrip(getattr(ex, part))
             if not rt.ok:
                 if len(self.samples) < self.keep_samples:
                     self.samples.append({"id": ex.id, "part": part, "at": rt.first_diff,
                                          "original": rt.original, "decoded": rt.decoded})
                 return False
-            n_tokens += rt.n_tokens
-        ex.n_tokens = n_tokens  # LengthFilter reuses this instead of encoding again
+            n_tokens += rt.n_tokens
+        ex.n_tokens = n_tokens  # LengthFilter reuses this instead of encoding again
         return True
 
 
 class LengthFilter(Filter):
@@
     def __init__(self, max_tokens: int, tokenizer: LocalTokenizer):
         self.max_tokens = max_tokens
         self.tokenizer = tokenizer
 
     def keep(self, ex: Example) -> bool:
-        if not ex.n_tokens:
-            ex.n_tokens = self.tokenizer.count(ex.prompt_text) + self.tokenizer.count(ex.target_text)
+        if not ex.n_tokens:
+            # Compute token count lazily if it hasn't been set by the
+            # DetokFilter (e.g., when detokenisation checking is disabled).
+            ex.n_tokens = self.tokenizer.count(ex.prompt_text) + self.tokenizer.count(ex.target_text)
         return ex.n_tokens <= self.max_tokens
*** End of File ***