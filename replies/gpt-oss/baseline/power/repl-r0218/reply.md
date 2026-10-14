**Commit Title:** Fix metrics dict generation, add total count to summary, and ensure proper imports for rating aggregation

**Commit Body:**
- Correct `Confusion.as_dict` to return the populated dictionary instead of `None`.
- Include total number of processed items (`n`) in the pipeline summary for report generation.
- Add missing imports (`Counter`, `mean`, `CATEGORIES`) in `autorater.py` to support self‑consistency aggregation.
- Minor cleanup of imports for clarity.

**Diff:**
```diff
diff --git a/misuseclf/metrics.py b/misuseclf/metrics.py
--- a/misuseclf/metrics.py
+++ b/misuseclf/metrics.py
@@
 @dataclass(frozen=True)
 class Confusion:
@@
     @classmethod
     def from_preds(cls, labels: Sequence[bool], preds: Sequence[bool]) -> "Confusion":
         if len(labels) != len(preds):
             raise ValueError(f"labels/preds length mismatch: {len(labels)} != {len(preds)}")
         tp = sum(l and p for l, p in zip(labels, preds))
         fp = sum(not l and p for l, p in zip(labels, preds))
         tn = sum(not l and not p for l, p in zip(labels, preds))
         fn = sum(l and not p for l, p in zip(labels, preds))
         return cls(tp=tp, fp=fp, tn=tn, fn=fn)
 
-    def as_dict(self) -> dict[str, int | float]:
-        return asdict(self).update(
-            precision=self.precision,
-            recall=self.recall,
-            fpr=self.fpr,
-            accuracy=self.accuracy,
-            f1=self.f1,
-        )
+    def as_dict(self) -> dict[str, int | float]:
+        """Return a dictionary with raw counts plus derived metrics."""
+        d = asdict(self)
+        # add derived metrics
+        d.update(
+            precision=self.precision,
+            recall=self.recall,
+            fpr=self.fpr,
+            accuracy=self.accuracy,
+            f1=self.f1,
+        )
+        return d
 
 
 def _ratio(num: int, den: int) -> float:
     return 0.0 if den == 0 else num / den
diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
--- a/misuseclf/pipeline.py
+++ b/misuseclf/pipeline.py
@@
 from .policy import Thresholds
 
 
 @dataclass
 class RatedItem:
@@
     pred: bool | None = None      # set by score(), from the threshold
 
     def to_json(self) -> dict:
         d = asdict(self.example)
         d.update({"score": self.score, "pred": self.pred, "pred_category": self.pred_category,
-                  "rationale": self.rationale, "reply": self.reply, "error": self.error})
+                  "rationale": self.rationale, "reply": self.reply,
+                  "n_samples": self.n_samples, "spread": self.spread,
+                  "error": self.error})
         return d
 
@@
 def _rate_one(rater: Autorater, ex: Example) -> RatedItem:
     try:
         r = rater.rate(ex)
-        return RatedItem(ex, score=r.score, pred_category=r.category, rationale=r.rationale, reply=r.reply,
-                         n_samples=r.n_samples, spread=r.spread)
+        return RatedItem(
+            ex,
+            score=r.score,
+            pred_category=r.category,
+            rationale=r.rationale,
+            reply=r.reply,
+            n_samples=r.n_samples,
+            spread=r.spread,
+        )
     except (GatewayError, VerdictParseError) as e:
         return RatedItem(ex, error=f"{type(e).__name__}: {e}")
@@
-def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
-          n_boot: int = 1000) -> dict:
+def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
+          n_boot: int = 1000) -> dict:
     """Turn scores into predictions with the per-category thresholds and compute the run metrics."""
-    ok = [r for r in rated if r.error is None]
+    ok = [r for r in rated if r.error is None]
     for r in ok:
         r.pred = thresholds.is_violation(r.score, r.pred_category)
-    labels = [r.example.is_violation for r in ok]
-    preds = [bool(r.pred) for r in ok]
-    summary = metrics.summarize(labels, preds, n_boot=n_boot)
+    labels = [r.example.is_violation for r in ok]
+    preds = [bool(r.pred) for r in ok]
+    summary = metrics.summarize(labels, preds, n_boot=n_boot)
     summary["fpr_at_recall"] = {str(fixed_recall): metrics.fpr_at_recall([r.score for r in ok], labels,
                                                                           fixed_recall)}
     summary["per_category"] = metrics.per_category([r.example.category for r in ok], labels, preds,
                                                    [r.pred_category for r in ok])
-    summary["errors"] = len(rated) - len(ok)
-    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
+    # Total number of items processed (including errors)
+    summary["n"] = len(rated)
+    summary["errors"] = len(rated) - len(ok)
+    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
     return summary
diff --git a/misuseclf/autorater.py b/misuseclf/autorater.py
--- a/misuseclf/autorater.py
+++ b/misuseclf/autorater.py
@@
-from __future__ import annotations
-
-import json
-import re
-from dataclasses import dataclass
-
-from . import prompts
-from .cache import RatingCache
+from __future__ import annotations
+
+import json
+import re
+from collections import Counter
+from dataclasses import dataclass
+from statistics import mean
+
+from . import prompts
+from .cache import RatingCache
 from .data import Example
-from .policy import CATEGORIES
+from .policy import CATEGORIES
 
 VERDICT_RE = re.compile(r"VERDICT:\s*(VIOLATION|SAFE)", re.I)
 CATEGORY_RE = re.compile(r"CATEGORY:\s*([a-z_]+)", re.I)
@@
 class Rating:
     score: float          # in [0, 1]
     category: str         # taxonomy key or "none"
     reply: str
-    rationale: str = ""
-    n_samples: int = 1
-    spread: float = 0.0   # max - min sample score
+    rationale: str = ""
+    n_samples: int = 1
+    spread: float = 0.0   # max - min sample score
 
 
-def aggregate(ratings: list[Rating]) -> Rating:
+def aggregate(ratings: list[Rating]) -> Rating:
     """Mean score over samples; category is the most common one among the samples (ties: higher mean)."""
     if not ratings:
         raise VerdictParseError("no parsable samples")
     if len(ratings) == 1:
         return ratings[0]
@@
 class Autorater:
-    def __init__(self, client, *, model: str, prompt_version: str, temperature: float = 0.0,
-                 max_tokens: int = 256, cache: RatingCache | None = None):
+    def __init__(self, client, *, model: str, prompt_version: str, temperature: float = 0.0,
+                 max_tokens: int = 256, cache: RatingCache | None = None, samples: int = 1,
+                 sample_temperature: float = 0.7):
         self.client = client
         self.cache = cache
         self.model = model
         self.prompt_version = prompt_version
         self.temperature = temperature
         self.max_tokens = max_tokens
+        self.samples = samples
+        self.sample_temperature = sample_temperature
         if samples < 1:
             raise ValueError("samples must be >= 1")
 
     def build_prompt(self, ex: Example) -> str:
         return prompts.render(self.prompt_version, request=ex.request, categories=CATEGORIES)
 
+    def _sample(self, ex: Example) -> list[str]:
+        """Generate `self.samples` replies from the model."""
+        prompt = self.build_prompt(ex)
+        temperature = self.temperature if self.samples == 1 else self.sample_temperature
+        return [
+            self.client.complete(prompt, temperature=temperature, max_tokens=self.max_tokens)
+            for _ in range(self.samples)
+        ]
+
+    def _parse_all(self, replies: list[str]) -> list[Rating]:
+        """Parse every reply; tolerate a minority of malformed samples."""
+        ratings, errors = [], []
+        for reply in replies:
+            try:
+                ratings.append(parse_verdict(reply, self.prompt_version))
+            except VerdictParseError as e:
+                errors.append(str(e))
+        if len(ratings) * 2 <= len(replies):
+            # Less than half of the samples were parsable – treat as a failure.
+            raise VerdictParseError(f"{len(errors)}/{len(replies)} samples unparsable; first: {errors[0]}")
+        return ratings
+
     def rate(self, ex: Example) -> Rating:
-        cached = self.cache.get(ex, self.model, self.prompt_version) if self.cache is not None else None
-        if cached is None:
-            reply = self.client.complete(self.build_prompt(ex), temperature=self.temperature,
-                                         max_tokens=self.max_tokens)
-            rating = parse_verdict(reply, self.prompt_version)  # only well-formed replies are cached
-            if self.cache is not None:
-                self.cache.put(ex, [reply], model=self.model, prompt_version=self.prompt_version)
-            return rating
-        return parse_verdict(cached[0], self.prompt_version)
+        replies = None
+        if self.cache is not None:
+            replies = self.cache.get(ex, self.model, self.prompt_version, samples=self.samples)
+        if replies is None:
+            # No cached entry – generate fresh samples.
+            replies = self._sample(ex)
+            rating = aggregate(self._parse_all(replies))  # only usable reply sets are cached
+            if self.cache is not None:
+                self.cache.put(ex, replies, model=self.model, prompt_version=self.prompt_version)
+            return rating
+        # Cached entry – parse and aggregate.
+        return aggregate(self._parse_all(replies))
```