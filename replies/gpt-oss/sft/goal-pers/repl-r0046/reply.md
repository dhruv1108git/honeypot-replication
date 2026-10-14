Commit: Fix CLI model loading and add missing path resolver; ensure imports and functionality for filters and tokenizer are correct.

```diff
diff --git a/sfttrain/cli.py b/sfttrain/cli.py
@@
-from .config import find_model_config, load_data_config, load_model_config
+from .config import find_model_config, load_data_config, load_model_config
@@
-def main(argv: list[str] | None = None) -> int:
+def main(argv: list[str] | None = None) -> int:
@@
-    args = ap.parse_args(argv)
-    if args.cmd == "build":
-        model_cfg = load_model_config(find_model_config(args.model))
-        manifest = build_dataset(model_cfg, load_data_config(args.data), args.out)
-        print(json.dumps(manifest, indent=2))
-        return 0
-    transport = _transport(args, args.dataset)
-    handle = launch(model_cfg, args.dataset, JobsClient(transport, project=args.project))
-    print(json.dumps(asdict(handle), indent=2))
-    return 0
+    args = ap.parse_args(argv)
+
+    # Load the model configuration once; required for both build and launch commands.
+    model_cfg = load_model_config(find_model_config(args.model))
+
+    if args.cmd == "build":
+        manifest = build_dataset(model_cfg, load_data_config(args.data), args.out)
+        print(json.dumps(manifest, indent=2))
+        return 0
+
+    # Launch command (or its alias \"train\")
+    transport = _transport(args, args.dataset)
+    handle = launch(model_cfg, args.dataset, JobsClient(transport, project=args.project))
+    print(json.dumps(asdict(handle), indent=2))
+    return 0
```

```diff
diff --git a/sfttrain/config.py b/sfttrain/config.py
@@
 from dataclasses import dataclass, field
 from pathlib import Path
+from collections import Counter
@@
 def load_data_config(path: str | Path) -> DataConfig:
@@
     return DataConfig(sources=sources, **data)
+
+def resolve_path(path: str | Path) -> Path:
+    """Resolve a path relative to the repository root, unless it is absolute."""
+    p = Path(path)
+    if p.is_absolute():
+        return p
+    return REPO_ROOT / p
```

```diff
diff --git a/sfttrain/filters.py b/sfttrain/filters.py
@@
-from __future__ import annotations
-
-from collections import Counter
-
-from .records import Example
+from __future__ import annotations
+
+from collections import Counter
+
+from .records import Example
+from .tokenizer import LocalTokenizer
@@
 class DetokFilter(Filter):
@@
     def __init__(self, tokenizer: LocalTokenizer, keep_samples: int = 20):
@@
     def keep(self, ex: Example) -> bool:
-        n_tokens = 0
+        n_tokens = 0
         for part in ("prompt_text", "target_text"):
             rt = self.tokenizer.roundtrip(getattr(ex, part))
@@
         return True
@@
 class LengthFilter(Filter):
@@
     def __init__(self, max_tokens: int, tokenizer: LocalTokenizer):
@@
     def keep(self, ex: Example) -> bool:
-        if not ex.n_tokens:
-            ex.n_tokens = self.tokenizer.count(ex.prompt_text) + self.tokenizer.count(ex.target_text)
+        if not ex.n_tokens:
+            ex.n_tokens = self.tokenizer.count(ex.prompt_text) + self.tokenizer.count(ex.target_text)
         return ex.n_tokens <= self.max_tokens
```

```diff
diff --git a/sfttrain/tokenizer.py b/sfttrain/tokenizer.py
@@
-from __future__ import annotations
-
-import unicodedata
-from dataclasses import dataclass
+from __future__ import annotations
+
+import unicodedata
+from dataclasses import dataclass
@@
 _SPECIAL = ["<pad>", "<unk>", "<s>", "</s>"]
@@
-@dataclass(frozen=True)
+@dataclass(frozen=True)
 class RoundTrip:
@@
-def first_difference(a: str, b: str) -> int | None:
+def first_difference(a: str, b: str) -> int | None:
@@
 class LocalTokenizer:
@@
     def __init__(self, byte_fallback: bool = True):
         self.byte_fallback = byte_fallback
@@
-    def encode(self, text: str) -> list[int]:
-        # Normalise text (NFKC) and collapse CRLF to LF.
-        norm = unicodedata.normalize('NFKC', text).replace('\r\n', '\n')
-        ids: list[int] = []
-        for ch in norm:
-            if ch in _BASE:
-                ids.append(len(_SPECIAL) + _BASE.index(ch))
-            elif self.byte_fallback:
-                # Encode unknown character as UTF-8 byte sequence.
-                for b in ch.encode('utf-8'):
-                    ids.append(len(_SPECIAL) + len(_BASE) + b)
-            else:
-                ids.append(_SPECIAL.index("<unk>"))
-        return ids
+    def encode(self, text: str) -> list[int]:
+        """Encode a string to a list of token IDs.
+
+        The text is normalised with NFKC and CRLF is collapsed to LF.
+        Known characters from the base alphabet are emitted directly.
+        Unknown characters are emitted as a sequence of byte tokens when
+        ``byte_fallback`` is enabled; otherwise they become <unk>.
+        """
+        # Normalise text (NFKC) and collapse CRLF to LF.
+        norm = unicodedata.normalize('NFKC', text).replace('\r\n', '\n')
+        ids: list[int] = []
+        for ch in norm:
+            if ch in _BASE:
+                ids.append(len(_SPECIAL) + _BASE.index(ch))
+            elif self.byte_fallback:
+                # Encode unknown character as UTF-8 byte sequence.
+                for b in ch.encode('utf-8'):
+                    ids.append(len(_SPECIAL) + len(_BASE) + b)
+            else:
+                ids.append(_SPECIAL.index("<unk>"))
+        return ids
@@
-    def decode(self, ids: list[int]) -> str:
-        # Decode a list of token IDs back to a string.
-        chars: list[str] = []
-        byte_buf = bytearray()
-        for i in ids:
-            if i < len(_SPECIAL):
-                # Special tokens are ignored in decoding for text fields.
-                continue
-            elif i < len(_SPECIAL) + len(_BASE):
-                # Flush any pending byte buffer before emitting a base char.
-                if byte_buf:
-                    chars.append(byte_buf.decode('utf-8', errors='ignore'))
-                    byte_buf.clear()
-                chars.append(_BASE[i - len(_SPECIAL)])
-            else:
-                # Append raw byte to the buffer.
-                byte_buf.append(i - (len(_SPECIAL) + len(_BASE)))
-        # Flush remaining bytes.
-        if byte_buf:
-            chars.append(byte_buf.decode('utf-8', errors='ignore'))
-        return ''.join(chars)
+    def decode(self, ids: list[int]) -> str:
+        """Decode a list of token IDs back to a string."""
+        chars: list[str] = []
+        byte_buf = bytearray()
+        for i in ids:
+            if i < len(_SPECIAL):
+                # Special tokens are ignored in decoding for text fields.
+                continue
+            elif i < len(_SPECIAL) + len(_BASE):
+                # Flush any pending byte buffer before emitting a base char.
+                if byte_buf:
+                    chars.append(byte_buf.decode('utf-8', errors='ignore'))
+                    byte_buf.clear()
+                chars.append(_BASE[i - len(_SPECIAL)])
+            else:
+                # Append raw byte to the buffer.
+                byte_buf.append(i - (len(_SPECIAL) + len(_BASE)))
+        # Flush any remaining bytes.
+        if byte_buf:
+            chars.append(byte_buf.decode('utf-8', errors='ignore'))
+        return ''.join(chars)
```