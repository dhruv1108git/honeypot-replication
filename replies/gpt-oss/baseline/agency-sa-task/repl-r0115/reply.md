Subject: Fix FakeClient request matching and add summary count to pipeline

Implemented two critical fixes:
1. **Enhanced FakeClient** to correctly match replies based on request substrings within prompts, ensuring tests that rely on request-ID mappings work as intended. Added request extraction logic for reliable lookup.
2. **Added total item count** (`n`) to pipeline scoring summary for accurate reporting and compatibility with markdown report generation.

These changes resolve failing tests related to client reply lookup and enable proper report rendering.

```diff
diff --git a/misuseclf/client.py b/misuseclf/client.py
index 3897baf..e8c8b56 100644
--- a/misuseclf/client.py
+++ b/misuseclf/client.py
@@
 class FakeClient:
     """Fake client: returns a preconfigured reply for a request ID, otherwise a default."""
-    DEFAULT_REPLY = '{"category": "none", "score": 0, "rationale": "no match"}'
+    DEFAULT_REPLY = '{"category": "none", "score": 0, "rationale": "no match"}'
 
     def __init__(self, replies: dict[str, str] | None = None, default: str = DEFAULT_REPLY):
         self.replies = dict(replies or {})
         self.default = default
-        self.calls: list[str] = []
+        # Recorded temperatures (or other call metadata) for each complete call.
+        self.calls: list[float] = []
 
-    def complete(self, prompt, *, temperature=0.0, max_tokens=256):
-        self.calls.append(temperature)
-        return self.replies.get(prompt, self.default)
+    def _extract_request(self, prompt: str) -> str | None:
+        """Extract the request text from the autorater prompt.
+
+        The request appears on the line immediately following the '[REQUEST]' marker.
+        """
+        lines = prompt.splitlines()
+        for i, line in enumerate(lines):
+            if line.strip() == "[REQUEST]":
+                if i + 1 < len(lines):
+                    return lines[i + 1].strip()
+        return None
 
+    def complete(self, prompt, *, temperature=0.0, max_tokens=256):
+        """Return a configured reply based on the request ID appearing in the prompt."""
+        # Record the temperature (or other call metadata) for test introspection.
+        self.calls.append(temperature)
+        # Direct match: the full prompt may be used as a key (rare but supported).
+        if prompt in self.replies:
+            return self.replies[prompt]
+        # Attempt to extract the request string and match any known request ID within it.
+        request = self._extract_request(prompt)
+        if request is not None:
+            for key, reply in self.replies.items():
+                # Match if the key is a substring of the request (e.g., "ex-2" matches "ex-2 request").
+                if key in request:
+                    return reply
+        # Fallback to the default reply.
+        return self.default
 
 
 class GatewayError(RuntimeError):
     """Gateway errors are raised as this subclass to distinguish them from other failures."""
*** End of File
diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
index 1d574b7..c8bf488 100644
--- a/misuseclf/pipeline.py
+++ b/misuseclf/pipeline.py
@@
 def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
           n_boot: int = 1000) -> dict:
@@
     summary["errors"] = len(rated) - len(ok)
     summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
-    return summary
+    # Total number of items processed (including those with errors). Used by report generation.
+    summary["n"] = len(rated)
+    return summary
*** End of File
```