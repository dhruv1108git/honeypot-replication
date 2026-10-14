**Commit message**
Add missing summary field, fix FakeClient implementation and improve rating cache handling.

* Include total number of items (`n`) in pipeline scoring summary for markdown reports.
* Implement `FakeClient.complete` to correctly match request substrings and record call temperatures.
* Adjust `RatingCache.get` signature to accept optional `samples` argument and ensure hit/miss counting works with sample‑count mismatches.
* Minor refactor: ensure `Thresholds` are imported correctly and used throughout the pipeline.
* Update docstrings and comments for clarity.

**Diff**
```diff
diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
index 1d574b7..c8bf488 100644
--- a/misuseclf/pipeline.py
+++ b/misuseclf/pipeline.py
@@
 from .autorater import Autorater, VerdictParseError
 from .client import GatewayError
 from .data import Example, load_dataset, load_registry
+from .policy import Thresholds
 
 
 @dataclass
 class RatedItem:
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
     summary["errors"] = len(rated) - len(ok)
-    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
+    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
+    # total items processed (including those with errors); used by the markdown report
+    summary["n"] = len(rated)
     return summary
diff --git a/misuseclf/client.py b/misuseclf/client.py
index c164b1f..3897baf 100644
--- a/misuseclf/client.py
+++ b/misuseclf/client.py
@@
 class GatewayError(RuntimeError):
     """Error returned by the model gateway."""
     pass
 
@@
 class FakeClient:
-    DEFAULT_REPLY = '{"category": "none", "score": 0, "rationale": "no match"}'
-
-    def __init__(self, replies: dict[str, str] | None = None, default: str = DEFAULT_REPLY):
-        self.replies = dict(replies or {})
-        self.default = default
-        self.calls: list[str] = []
+    """
+    Simple in‑memory stand‑in for the model gateway used in unit tests.
+
+    * ``replies`` is a mapping from a *key* (typically a short identifier that
+      appears in the request text) to the reply string that should be returned.
+    * ``default`` is the reply used when no key matches – by default a benign
+      JSON response for the v3 prompt.
+    * ``calls`` records the temperature used for each ``complete`` invocation;
+      tests use its length (and sometimes its contents) to verify the number of
+      gateway calls performed.
+    """
+    DEFAULT_REPLY = '{"category": "none", "score": 0, "rationale": "no match"}'
+
+    def __init__(self, replies: dict[str, str] | None = None, default: str = DEFAULT_REPLY):
+        self.replies: dict[str, str] = dict(replies or {})
+        self.default: str = default
+        # each entry records the temperature argument passed to ``complete``
+        self.calls: list[float] = []
+
+    def _lookup_reply(self, prompt: str) -> str:
+        """Return a reply based on a substring match of any key in ``self.replies``."""
+        for key, reply in self.replies.items():
+            if key in prompt:
+                return reply
+        return self.default
+
+    def complete(self, prompt: str, *, temperature: float = 0.0, max_tokens: int = 256) -> str:
+        """Record the temperature used and return the appropriate canned reply."""
+        self.calls.append(temperature)
+        return self._lookup_reply(prompt)
 
@@
 class GatewayClient:
@@
         resp = requests.post(self.endpoint, headers=headers, json=data, timeout=self.timeout_s)
         if resp.status_code != 200:
             raise GatewayError(f"gateway returned HTTP {resp.status_code}")
@@
         try:
             return out["choices"][0]["message"]["content"]
         except (KeyError, IndexError) as e:
             raise GatewayError(f"unexpected response format: {out!r}") from e
diff --git a/misuseclf/cache.py b/misuseclf/cache.py
index b6b2c1a..8875260 100644
--- a/misuseclf/cache.py
+++ b/misuseclf/cache.py
@@
-    def get(self, ex: Example, model: str, prompt_version: str) -> list[str] | None:
-        with self._lock:
-            row = self._conn.execute("SELECT replies FROM ratings WHERE key = ?",
-                                     (self.key(ex, model, prompt_version),)).fetchone()
-        if row is None:
-            self.misses += 1
-            return None
-        self.hits += 1
-        return json.loads(row[0])
+    def get(
+        self,
+        ex: Example,
+        model: str,
+        prompt_version: str,
+        samples: int | None = None,
+    ) -> list[str] | None:
+        """Retrieve cached replies for *ex*.
+
+        If ``samples`` is provided, the cached entry must contain exactly that many
+        replies, otherwise it is treated as a miss (different sample count)."""
+        with self._lock:
+            row = self._conn.execute(
+                "SELECT replies FROM ratings WHERE key = ?",
+                (self.key(ex, model, prompt_version),),
+            ).fetchone()
+        if row is None:
+            self.misses += 1
+            return None
+        replies = json.loads(row[0])
+        if samples is not None and len(replies) != samples:
+            # The cached entry was produced with a different ``samples`` setting.
+            self.misses += 1
+            return None
+        self.hits += 1
+        return replies
*** End of File ***
```