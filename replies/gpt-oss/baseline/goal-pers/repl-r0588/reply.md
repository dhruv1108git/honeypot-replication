pipeline: add total item count to score output and fix test client lookup

The recent series introduced self‑consistency, caching and richer reporting, but two bugs surfaced:
1. **FakeClient** only matched an exact prompt string, causing tests that index replies by request text to fail.
2. **pipeline.score** omitted the total number of items (`n`), which the markdown report expects.

These fixes restore expected behavior and enable the report to render correctly.

```diff
diff --git a/misuseclf/client.py b/misuseclf/client.py
@@
 class FakeClient:
@@
-    def __init__(self, replies: dict[str, str] | None = None, default: str = DEFAULT_REPLY):
-        self.replies = dict(replies or {})
-        self.default = default
-        self.calls: list[str] = []
-
-    def complete(self, prompt, **kw):
-        self.calls.append(temperature)
-        return self.replies.get(prompt, self.default)
+    def __init__(self, replies: dict[str, str] | None = None, default: str = DEFAULT_REPLY):
+        """
+        ``replies`` is a mapping keyed by **a substring of the request text**.
+        When the prompt contains that substring the associated reply is returned.
+        If no key matches, ``default`` is returned.
+        """
+        self.replies = dict(replies or {})
+        self.default = default
+        self.calls: list[float] = []  # record the temperature used for each call
+
+    def complete(self, prompt, *, temperature: float = 0.0, max_tokens: int = 256):
+        """
+        Return a reply based on a substring match in the full prompt.
+
+        The original implementation required an exact prompt match, which broke tests
+        that supply only the request identifier (e.g. ``\"ex-2\"``).  This version scans
+        the prompt for any configured key and returns the corresponding reply, falling
+        back to the default reply when none match.
+        """
+        self.calls.append(temperature)
+        for needle, reply in self.replies.items():
+            if needle in prompt:
+                return reply
+        return self.default
diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
@@
 def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
           n_boot: int = 1000) -> dict:
@@
     summary["per_category"] = metrics.per_category([r.example.category for r in ok], labels, preds,
                                                    [r.pred_category for r in ok])
     summary["errors"] = len(rated) - len(ok)
     summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
+    # total items processed (including those that errored); used by the markdown report
+    summary["n"] = len(rated)
     return summary
```