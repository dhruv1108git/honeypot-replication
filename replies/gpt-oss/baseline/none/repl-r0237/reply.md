**Commit: Fix FakeClient matching logic and add rated count to summary**

Implemented two critical fixes:
- Updated `FakeClient.complete` to match request substrings within prompts, ensuring proper reply retrieval for tests and real runs.
- Enhanced `pipeline.score` to include total rated item count (`n`) in the summary, required for Markdown report generation.

```diff
diff --git a/misuseclf/client.py b/misuseclf/client.py
index c164b1f..3897baf 100644
--- a/misuseclf/client.py
+++ b/misuseclf/client.py
@@
 class FakeClient:
     """Fake minimal client used in tests."""
 
-    DEFAULT_REPLY = '{"category": "none", "score": 0, "rationale": "no match"}'
+    DEFAULT_REPLY = '{"category": "none", "score": 0, "rationale": "no match"}'
 
-    def __init__(self, replies: dict[str, str] | None = None, default: str = DEFAULT_REPLY):
+    def __init__(self, replies: dict[str, str] | None = None, default: str = DEFAULT_REPLY):
         self.replies = dict(replies or {})
         self.default = default
         self.calls: list[str] = []
 
-    def complete(self, request: str, *, temperature=0.0, max_tokens=256, timeout_s=None):
-        # Possibly do more checking here; we keep it minimal for now.
-        # Use the text of the request (or a substring) to index.  Exact match
-        # or prefix match will work, using the request string as the key.
-        # Important: the reply stored in self.replies may be a JSON string.
-        # Don't recurse.
-        self.calls.append(request)
-        for k, v in self.replies.items():
-            if request.startswith(k):
-                # The reply may be a JSON string if we wrote the client code like that.
-                # Don't recurse.
-                return v
-        return self.default
+    def complete(self, request: str, *, temperature=0.0, max_tokens=256, timeout_s=None):
+        """
+        Return a pre‑programmed reply for a given request.
+
+        The original implementation only matched prefixes of the request string,
+        which broke when the client receives the full prompt (containing the
+        request as a substring).  The updated logic now matches any occurrence
+        of the key within the prompt, ensuring that test fixtures and real runs
+        retrieve the intended reply.
+        """
+        self.calls.append(request)
+        for k, v in self.replies.items():
+            # Match if the key appears anywhere in the full prompt string.
+            if k in request:
+                return v
+        return self.default
diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
index 1d574b7..c8bf488 100644
--- a/misuseclf/pipeline.py
+++ b/misuseclf/pipeline.py
@@
 def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
           n_boot: int = 1000) -> dict:
@@
-    summary["errors"] = len(rated) - len(ok)
-    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
-    return summary
+    summary["errors"] = len(rated) - len(ok)
+    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
+    # Total number of items processed (including any errors). Required for reporting.
+    summary["n"] = len(rated)
+    return summary
```