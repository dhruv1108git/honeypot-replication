Fix FakeClient request extraction and add total count to score summary

* Updated `misuseclf/client.py`:
  - Implemented robust request extraction from prompts.
  - Added handling for reply lookup using request substring matching.
  - Recorded the temperature for each call in `self.calls`.
  - Returned appropriate reply or default when no mapping is found.
* Updated `misuseclf/pipeline.py`:
  - Added total number of items (`n`) to the summary returned by `score`.
  - Ensured this field is present for downstream reporting.

```diff
--- a/misuseclf/client.py
+++ b/misuseclf/client.py
@@
 class FakeClient:
     DEFAULT_REPLY = '{"category": "none", "score": 0, "rationale": "no match"}'
 
     def __init__(self, replies: dict[str, str] | None = None, default: str = DEFAULT_REPLY):
         self.replies = dict(replies or {})
         self.default = default
-        self.calls: list[str] = []
+        self.calls: list[float] = []  # store temperature values for each call
 
-    def complete(self, prompt, *, temperature=0.0, max_tokens=256):
-        self.calls.append(temperature)
-        # Determine key. In earlier tests they use a dictionary mapping from request string to reply.
-        # The key in replies is the request identifier (e.g., "ex-2") which appears in the request line.
-        # Extract the request line after the "[REQUEST]" marker.
-        request = ""
-        if "[REQUEST]" in prompt:
-            # Find the line after the marker
-            parts = prompt.split("[REQUEST]")
-            if len(parts) > 1:
-                after = parts[1].lstrip()
-                request = after.splitlines()[0].strip()
-        # Fallback to full prompt if extraction fails
-        key = request or prompt
-        # Return the mapped reply if it exists, otherwise the default
-        return self.replies.get(key, self.default)
+    def _extract_request(self, prompt: str) -> str:
+        """Extract the request string from the rendered prompt.
+
+        The prompt template inserts a line with ``[REQUEST]`` followed by the
+        request on the next line.  This method returns that line (stripped of
+        surrounding whitespace).  If the marker is missing, the empty string
+        is returned.
+        """
+        marker = "[REQUEST]"
+        if marker not in prompt:
+            return ""
+        # Split on the marker and take the text after it
+        after = prompt.split(marker, 1)[1].lstrip()
+        # The request is the first line after the marker
+        request_line = after.splitlines()[0].strip()
+        return request_line
 
-    def __init__(self, replies: dict[str, str] | None = None, default: str = DEFAULT_REPLY):
-        self.replies = dict(replies or {})
-        self.default = default
-        self.calls: list[str] = []
+    def complete(self, prompt: str, *, temperature: float = 0.0, max_tokens: int = 256) -> str:
+        """Return a fake reply for the given prompt.
+
+        The function records the temperature used for the call (useful for
+        self‑consistency tests) and returns a reply based on the request
+        extracted from the prompt.  If a matching key is found in ``self.replies``,
+        that reply is returned; otherwise ``self.default`` is used.
+        """
+        # Record temperature for test assertions
+        self.calls.append(temperature)
+
+        request = self._extract_request(prompt)
+        # Match using substring containment: find the first key that appears in the request
+        for key, reply in self.replies.items():
+            if key and key in request:
+                return reply
+        # No specific match – fall back to the default reply
+        return self.default
 
*** End of File ***
--- a/misuseclf/pipeline.py
+++ b/misuseclf/pipeline.py
@@
 def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
           n_boot: int = 1000) -> dict:
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
+    # Total number of items processed (including errors)
+    summary["n"] = len(rated)
     return summary
```