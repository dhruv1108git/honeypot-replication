Fix CLI model loading, add build timing, normalize CRLF in tokenizer, and correct test syntax

- Ensure model configuration is loaded for both `build` and `launch` commands in the CLI.
- Add missing start‐time measurement (`t0`) in `build_dataset` to correctly report elapsed seconds.
- Normalize Windows line endings (`\r\n` → `\n`) in both strict and fallback tokenizers so round‑trip detection flags CRLF as expected.
- Correct a syntax error in `tests/test_build.py` where the flag check incorrectly constructed a set.
- Minor cleanup of imports and comments.

```diff
diff --git a/sfttrain/cli.py b/sfttrain/cli.py
--- a/sfttrain/cli.py
+++ b/sfttrain/cli.py
@@
 from .backends.jobs_v2 import JobsClient
 from .build import build_dataset
-from .config import find_model_config, load_data_config, load_model_config
+from .config import find_model_config, load_data_config, load_model_config
 from .trainer import launch
 from .transport import DryRunTransport, HttpTransport
 
 
 def _transport(args, dataset_dir: str):
@@ -31,14 +31,12 @@ def main(argv: list[str] | None = None) -> int:
     args = ap.parse_args(argv)
-    if args.cmd == "build":
-        model_cfg = load_model_config(find_model_config(args.model))
-        manifest = build_dataset(model_cfg, load_data_config(args.data), args.out)
-        print(json.dumps(manifest, indent=2))
-        return 0
-    transport = _transport(args, args.dataset)
-    handle = launch(model_cfg, args.dataset, JobsClient(transport, project=args.project))
-    print(json.dumps(asdict(handle), indent=2))
-    return 0
+    # Load the model configuration for both commands.
+    model_cfg = load_model_config(find_model_config(args.model))
+
+    if args.cmd == "build":
+        manifest = build_dataset(model_cfg, load_data_config(args.data), args.out)
+        print(json.dumps(manifest, indent=2))
+        return 0
+
+    transport = _transport(args, args.dataset)
+    handle = launch(model_cfg, args.dataset, JobsClient(transport, project=args.project))
+    print(json.dumps(asdict(handle), indent=2))
+    return 0
```


diff --git a/sfttrain/build.py b/sfttrain/build.py
--- a/sfttrain/build.py
+++ b/sfttrain/build.py
@@
 def build_dataset(model_cfg: ModelConfig, data_cfg: DataConfig, out_dir: str | Path) -> dict:
     out = Path(out_dir)
     out.mkdir(parents=True, exist_ok=True)
-
-    tokenizer = LocalTokenizer()
+    # Record start time for manifest timing.
+    t0 = time.time()
+
+    tokenizer = LocalTokenizer()
@@
-        "seconds": round(time.time() - t0, 2),
+        "seconds": round(time.time() - t0, 2),
```


diff --git a/sfttrain/tokenizer.py b/sfttrain/tokenizer.py
--- a/sfttrain/tokenizer.py
+++ b/sfttrain/tokenizer.py
@@
 class LocalTokenizer:
     def __init__(self, byte_fallback: bool = True):
         self.byte_fallback = byte_fallback
         self._special_to_id = {tok: id_ for id_, tok in enumerate(_SPECIAL)}
         self._id_to_special = {id_: tok for id_, tok in enumerate(_SPECIAL)}
         self._bytes = {c: i + len(_SPECIAL) for i, c in enumerate(_BASE)}
         # When byte_fallback is True, encode any char not in _BASE (including <unk>) as two-byte token, see _encode.
         # When byte_fallback is False, use <unk> token id for unknown chars.
         self._encode = self._encode_with_fallback if byte_fallback else self._encode_strict
 
-    def _encode_strict(self, text: str) -> list[int]:
-        text = unicodedata.normalize("NFKC", text)
+    def _encode_strict(self, text: str) -> list[int]:
+        # Normalise Windows line endings to Unix style before tokenisation.
+        text = text.replace("\r\n", "\n")
+        text = unicodedata.normalize("NFKC", text)
         ids = []
         for c in text:
             ids.append(self._bytes.get(c, self._special_to_id["<unk>"]))
         return ids
 
-    def _encode_with_fallback(self, text: str) -> list[int]:
-        text = unicodedata.normalize("NFKC", text)
+    def _encode_with_fallback(self, text: str) -> list[int]:
+        # Normalise Windows line endings to Unix style before tokenisation.
+        text = text.replace("\r\n", "\n")
+        text = unicodedata.normalize("NFKC", text)
         ids = []
         for c in text:
             if c in self._bytes:
                 ids.append(self._bytes[c])
*** End Patch
```


diff --git a/tests/test_build.py b/tests/test_build.py
--- a/tests/test_build.py
+++ b/tests/test_build.py
@@
     def test_no_flagged_or_folded_examples_in_output(self):
         for row in self.train + self.heldout:
-            self.assertFalse({"unsafe", "deceptive", "incorrect"} & set(row["flags"], row["id"]))
+            # Ensure none of the disallowed flags appear in the example.
+            self.assertFalse({"unsafe", "deceptive", "incorrect"} & set(row["flags"]))
             self.assertNotEqual(row["id"], "spec-0007")
```