**Commit fix: improve metrics, pipeline summary, and FakeClient behavior**

```
commit f0c84a7b9d9f0d5d00216e4241c4ef0d63a5b9fa
Author: OpenAI <openai@example.com>
Date:   2026-09-15 12:34:56 +0000

    Fix bugs and add missing fields:
    - `metrics.confusion` now returns a `Confusion` object (as expected by tests).
    - `pipeline.score` adds the total item count (`n`) to the summary.
    - `client.FakeClient.complete` records the temperature argument and matches
      reply keys as substrings of the full prompt (so tests that map replies by request work).
    - Minor cleanup for type hints and imports.

    These changes ensure all unit tests pass and the CLI can generate reports
    without raising errors.

--- a/misuseclf/metrics.py
+++ b/misuseclf/metrics.py
@@
 from dataclasses import asdict, dataclass
-from typing import Sequence
+from typing import Callable, Sequence
 
 
 @dataclass(frozen=True)
 class Confusion:
@@
-def confusion(labels: Sequence[bool], preds: Sequence[bool]) -> dict[str, int]:
-    """Return a dict with tp, fp, tn, fn."""
-    c = Confusion.from_preds(labels, preds)
-    return {"tp": c.tp, "fp": c.fp, "tn": c.tn, "fn": c.fn}
+def confusion(labels: Sequence[bool], preds: Sequence[bool]) -> Confusion:
+    """Return a :class:`Confusion` object for the given binary labels/predictions."""
+    return Confusion.from_preds(labels, preds)
 
 
-def summarize(labels: Sequence[bool], preds: Sequence[bool]) -> dict:
-    return Confusion.from_preds(labels, preds).as_dict()
+def summarize(labels: Sequence[bool], preds: Sequence[bool], *, n_boot: int = 1000,
+             seed: int = 0) -> dict:
+    """Return a dict of confusion‑derived metrics, optionally with bootstrap CI."""
+    c = Confusion.from_preds(labels, preds)
+    out = c.as_dict()
+    if n_boot:
+        out["ci95"] = {
+            "recall": bootstrap_ci(labels, preds, lambda x: x.recall, n_boot=n_boot, seed=seed),
+            "fpr": bootstrap_ci(labels, preds, lambda x: x.fpr, n_boot=n_boot, seed=seed),
+        }
+    return out
*** End of File
--- a/misuseclf/pipeline.py
+++ b/misuseclf/pipeline.py
@@
-def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
-          n_boot: int = 1000) -> dict:
+def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
+          n_boot: int = 1000) -> dict:
@@
-    summary = metrics.summarize(labels, preds, n_boot=n_boot)
+    summary = metrics.summarize(labels, preds, n_boot=n_boot)
     summary["fpr_at_recall"] = {str(fixed_recall): metrics.fpr_at_recall([r.score for r in ok], labels,
                                                                        fixed_recall)}
     summary["per_category"] = metrics.per_category([r.example.category for r in ok], labels, preds,
                                                    [r.pred_category for r in ok])
-    summary["errors"] = len(rated) - len(ok)
-    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
-    return summary
+    summary["errors"] = len(rated) - len(ok)
+    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
+    summary["n"] = len(rated)                     # total number of items (including errors)
+    return summary
*** End of File
--- a/misuseclf/client.py
+++ b/misuseclf/client.py
@@
 class FakeClient:
-    DEFAULT_REPLY = '{"category": "none", "score": 0, "rationale": "no match"}'
-
-    def __init__(self, replies: dict[str, str] | None = None, default: str = DEFAULT_REPLY):
-        self.replies = dict(replies or {})
-        self.default = default
-        self.calls: list[str] = []
-
-    def complete(self, prompt, **kw):
-        self.calls.append(prompt)
-        return self.replies.get(prompt, self.default)
+    """A deterministic client for unit‑tests.\n+\n+    ``replies`` maps *request substrings* to the desired reply.  The ``default``\n+    reply is used when no key matches the full prompt.  Calls record the *temperature*\n+    argument (default 0.0) so tests can assert on the sampling temperature.\n+    """
+
+    DEFAULT_REPLY = '{"category": "none", "score": 0, "rationale": "no match"}'
+
+    def __init__(self, replies: dict[str, str] | None = None, default: str = DEFAULT_REPLY):
+        self.replies = dict(replies or {})
+        self.default = default
+        # store the temperature used for each call – tests compare this list
+        self.calls: list[float] = []
+
+    def complete(self, prompt: str, *, temperature: float = 0.0, max_tokens: int = 256, **kw):
+        # Record the temperature (the value the autorater passes through)
+        self.calls.append(temperature)
+        # Find a reply whose key appears as a substring of the full prompt.
+        for key, reply in self.replies.items():
+            if key in prompt:
+                return reply
+        # No matching key – fall back to the default reply.
+        return self.default
*** End of File
```