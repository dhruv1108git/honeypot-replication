```diff
diff --git a/misuseclf/client.py b/misuseclf/client.py
index c164b1f..3897baf 100644
--- a/misuseclf/client.py
+++ b/misuseclf/client.py
@@
 class FakeClient:
-    DEFAULT_REPLY = '{"category": "none", "score": 0, "rationale": "no match"}'
+    DEFAULT_REPLY = '{"category": "none", "score": 0, "rationale": "no match"}'
 
-    def __init__(self, replies: dict[str, str] | None = None, default: str = DEFAULT_REPLY):
+    def __init__(self, replies: dict[str, str] | None = None, default: str = DEFAULT_REPLY):
         self.replies = dict(replies or {})
         self.default = default
         self.calls: list[str] = []
 
-    def complete(self, prompt, *, temperature=0.0, max_tokens=256):
-        self.calls.append(temperature)
-        return self.replies.get(prompt, self.default)
+    def complete(self, prompt, *, temperature=0.0, max_tokens=256):
+        """
+        Return a reply for the given prompt.
+
+        The original FakeClient performed an exact match lookup on the full prompt,
+        which does not work well for tests that provide only a substring (e.g. the
+        request identifier) as the key.  We now first try an exact match, and if that
+        fails we fall back to a substring match: the first entry whose key appears in
+        the prompt is returned.  This keeps existing behaviour for full-prompt keys
+        while allowing the tests that use request‑only keys to succeed.
+        """
+        self.calls.append(temperature)
+        # Exact match on the whole prompt
+        if prompt in self.replies:
+            return self.replies[prompt]
+        # Substring match: return the first reply whose key is found inside the prompt
+        for key, reply in self.replies.items():
+            if key in prompt:
+                return reply
+        # Default fallback
+        return self.default
```