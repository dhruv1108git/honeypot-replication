backends add client for the jobs v2 training API

More fixes for the data pipeline:

- Fix off‑by‑one error in `truncate_thought` to correctly keep the last `max_tokens` tokens.
- Make source weighting deterministic by using a stable SHA‑256 hash instead of Python’s
  built‑in `hash` (which is salted per interpreter). This ensures reproducible results
  when a source weight is < 1.

These changes improve the correctness of thought truncation and the determinism of
source subsampling.

```diff
diff --git a/sfttrain/templates.py b/sfttrain/templates.py
index 4a30fd6..e8c9e0a 100644
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
+        return text, False
+    # Keep exactly the last `max_tokens` token ids.
+    truncated_ids = ids[-max_tokens:]
+    return tokenizer.decode(truncated_ids).lstrip(), True
```

```diff
diff --git a/sfttrain/mixture.py b/sfttrain/mixture.py
index 277d633..c2f8e1a 100644
--- a/sfttrain/mixture.py
+++ b/sfttrain/mixture.py
@@
-from .config import DataConfig, SourceConfig, resolve_path
+import hashlib
+from .config import DataConfig, SourceConfig, resolve_path
@@
-def weighted(examples: list[Example], weight: float, rng: random.Random) -> list[Example]:
-    out = []
-    if weight >= 1:
-        repeats = int(weight)
-        for _ in range(repeats):
-            out.extend(examples)
-        # repeat fractional part by deterministic subsampling
-        extra = weight - repeats
-        if extra > 0:
-            out.extend(weighted(examples, extra, rng))
-    elif weight > 0:
-        # deterministic subsample: keep a fraction `weight` of examples,
-        # selected by a stable hash of (id, seed)
-        for ex in examples:
-            h = hash((ex.id, rng.getstate()))
-            # use low bits to map to [0,1)
-            if (h & ((1 << 30) - 1)) / float(1 << 30) < weight:
-                out.append(ex)
-    return out
+def _stable_hash(value: str) -> int:
+    """Return a deterministic hash of `value` as an integer."""
+    # Use SHA‑256 for stability across interpreter restarts.
+    return int(hashlib.sha256(value.encode("utf-8")).hexdigest(), 16)
+
+
+def weighted(examples: list[Example], weight: float, rng: random.Random) -> list[Example]:
+    """Apply a source weight to a list of examples.
+
+    * weight >= 1   → repeat the examples ``int(weight)`` times, then
+      possibly add a fractional part by deterministic subsampling.
+    * 0 < weight < 1 → keep a fraction ``weight`` of the examples,
+      chosen deterministically using a stable hash of each example’s ID.
+    """
+    out: list[Example] = []
+    if weight >= 1:
+        repeats = int(weight)
+        for _ in range(repeats):
+            out.extend(examples)
+        # Handle the fractional part (e.g. weight 2.5) via a deterministic subsample.
+        extra = weight - repeats
+        if extra > 0:
+            out.extend(weighted(examples, extra, rng))
+    elif weight > 0:
+        # Deterministic subsample: keep a fraction `weight` of examples,
+        # using a stable SHA‑256 hash of the example ID.
+        for ex in examples:
+            h = _stable_hash(ex.id)
+            # Map the low 30 bits of the hash to a float in [0, 1).
+            if (h & ((1 << 30) - 1)) / float(1 << 30) < weight:
+                out.append(ex)
+    return out
```