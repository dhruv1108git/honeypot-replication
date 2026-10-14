**Fix import error in autorater and improve FakeClient behaviour**

- Remove incorrect import of `VerdictParseError` from `policy` (it is defined locally in `autorater`).
- Refactor `FakeClient` in `client.py`:
  - Store call temperatures as `float` values.
  - Extract request keys from prompts (last non‑empty line, first token) so test mappings work.
  - Provide clearer inline documentation and adjust type hints.

These changes resolve import failures and ensure the FakeClient correctly matches request keys and logs temperature values, allowing all unit tests to pass.

```diff
diff --git a/misuseclf/autorater.py b/misuseclf/autorater.py
--- a/misuseclf/autorater.py
+++ b/misuseclf/autorater.py
@@
-from .policy import CATEGORIES, VerdictParseError
+from .policy import CATEGORIES
@@
 class VerdictParseError(ValueError):
     """The model's reply did not contain a usable verdict."""
*** End of File ***
diff --git a/misuseclf/client.py b/misuseclf/client.py
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
-    def complete(self, prompt: str, *, temperature=0.0, max_tokens=256):
-        """Return a canned reply based on the request extracted from the prompt.
-
-        The request is taken as the last non‑empty line of the prompt; the first
-        whitespace‑separated token of that line is used as the lookup key.
-        The method records the temperature used for each call (as a float) in
-        ``self.calls`` – tests rely on this to verify the correct temperature
-        is applied when sampling multiple times.
-        """
-        self.calls.append(temperature)
-        # Extract the request part from the prompt. The request is the last
-        # non‑empty line of the rendered prompt.
-        lines = [ln for ln in prompt.splitlines() if ln.strip()]
-        if not lines:
-            key = ""
-        else:
-            request_line = lines[-1].strip()
-            # Use the first token of the request line as the key (matches test
-            # expectations where the mapping may use a shortened identifier).
-            key = request_line.split()[0]
-        return self.replies.get(key, self.default)
+    DEFAULT_REPLY = '{"category": "none", "score": 0, "rationale": "no match"}'
+
+    def __init__(self, replies: dict[str, str] | None = None, default: str = DEFAULT_REPLY):
+        """
+        Initialize the fake client.
+
+        * ``replies`` – a mapping from a request identifier to the reply that
+          the client should return.  The identifier is the first token of the
+          request line extracted from the rendered prompt.
+        * ``default`` – the reply to use when the request identifier is not
+          present in ``replies``.  By default this is a valid JSON verdict with
+          a zero score.
+        """
+        self.replies = dict(replies or {})
+        self.default = default
+        # Store the temperatures used for each call (as floats).  Tests assert
+        # on this list directly.
+        self.calls: list[float] = []
+
+    def _extract_key(self, prompt: str) -> str:
+        """
+        Extract the request identifier from a rendered prompt.
+
+        The prompt always ends with the request text on its own line.
+        We take the last non‑empty line, split on whitespace and use the
+        first token as the key.  This works for both the simple identifiers
+        used in the tests (e.g. ``ex-2``) and full request strings that contain
+        spaces (e.g. ``[req fraud-1]``).
+        """
+        lines = [ln for ln in prompt.splitlines() if ln.strip()]
+        if not lines:
+            return ""
+        request_line = lines[-1].strip()
+        return request_line.split()[0]
+
+    def complete(self, prompt: str, *, temperature: float = 0.0, max_tokens: int = 256) -> str:
+        """
+        Return a canned reply based on the extracted request key.
+
+        The method records the temperature used for the call in ``self.calls``.
+        """
+        self.calls.append(temperature)
+        key = self._extract_key(prompt)
+        return self.replies.get(key, self.default)
*** End of File ***
```