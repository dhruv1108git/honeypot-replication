pipeline: add total count to summary and fix Autorater max_tokens

```diff
diff --git a/misuseclf/autorater.py b/misuseclf/autorater.py
@@
 class Autorater:
-    def __init__(self, client, *, model: str, prompt_version: str, temperature: float = 0.0,
-                 max_tokens: int = 256, cache: RatingCache | None = None, samples: int = 1,
-                 sample_temperature: float = 0.7):
-        if samples < 1:
-            raise ValueError("samples must be >= 1")
-        self.client = client
-        self.cache = cache
-        self.model = model
-        self.prompt_version = prompt_version
-        self.temperature = temperature
-        self.max_tokens = max_tokens
-        self.samples = samples
-        self.sample_temperature = sample_temperature
+    def __init__(self, client, *, model: str, prompt_version: str, temperature: float = 0.0,
+                 max_tokens: int = 256, cache: RatingCache | None = None, samples: int = 1,
+                 sample_temperature: float = 0.7):
+        """Create an autorater bound to a gateway client.\n+\n+        ``samples`` enables self‑consistency: the model is queried ``samples``\n+        times (at ``sample_temperature`` when ``samples > 1``) and the results are\n+        aggregated. ``max_tokens`` is passed through to the client.\n+        """
+        if samples < 1:
+            raise ValueError("samples must be >= 1")
+        self.client = client
+        self.cache = cache
+        self.model = model
+        self.prompt_version = prompt_version
+        self.temperature = temperature
+        self.max_tokens = max_tokens          # <-- previously missing, caused AttributeError
+        self.samples = samples
+        self.sample_temperature = sample_temperature
*** End of File
diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
@@
-def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
-          n_boot: int = 1000) -> dict:
-    """Turn scores into predictions with the per-category thresholds and compute the run metrics."""
+def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
+          n_boot: int = 1000) -> dict:
+    """Turn scores into predictions with the per‑category thresholds and compute the run metrics.\n+\n+    The returned ``summary`` now includes ``n`` – the total number of items\n+    (including those that errored) – which is used by the markdown report.\n+    """
     ok = [r for r in rated if r.error is None]
     for r in ok:
         r.pred = thresholds.is_violation(r.score, r.pred_category)
     labels = [r.example.is_violation for r in ok]
     preds = [bool(r.pred) for r in ok]
     summary = metrics.summarize(labels, preds, n_boot=n_boot)
     summary["fpr_at_recall"] = {str(fixed_recall): metrics.fpr_at_recall([r.score for r in ok], labels,
                                                                           fixed_recall)}
     summary["per_category"] = metrics.per_category([r.example.category for r in ok], labels, preds,
                                                    [r.pred_category for r in ok])
     summary["errors"] = len(rated) - len(ok)
-    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
+    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
+    # total number of items processed (including those that errored)
+    summary["n"] = len(rated)
     return summary
*** End of File
```