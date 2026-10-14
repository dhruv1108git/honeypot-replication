commit 9f8e1b2
Author: OpenAI <assistant@openai.com>
Date:   2026-09-15 12:00:00 +0000

    fix: off‑by‑one in thought truncation and ensure dry‑run transport returns status

    * Correct `truncate_thought` to keep exactly the last `max_tokens` tokens.
    * Enhance `DryRunTransport` to write request bodies to the expected filename
      (`v2_jobs.json` for the Jobs V2 API) and return a dummy response with
      `job_id` and `status` set to `"dry_run"` so the launcher sees a dry‑run
      result.
    * Add documentation/comments and ensure imports are present.

diff --git a/sfttrain/templates.py b/sfttrain/templates.py
index 4a30fd6..a2c3f01 100644
--- a/sfttrain/templates.py
+++ b/sfttrain/templates.py
@@
-def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tuple[str, bool]:
-    """Keep the last `max_tokens` tokens of the reasoning.
-
-    The end of the reasoning is where the model settles on its answer, so
-    that is the part we keep when we have to cut. Returns (text, truncated).
-    """
-    ids = tokenizer.encode(text)
-    if len(ids) <= max_tokens:
-        return text, False
-    return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True
+def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tuple[str, bool]:
+    """Keep the last `max_tokens` tokens of the reasoning.
+
+    The end of the reasoning is where the model settles on its answer, so
+    that is the part we keep when we have to cut. Returns (text, truncated).
+    """
+    ids = tokenizer.encode(text)
+    if len(ids) <= max_tokens:
+        return text, False
+    # Keep exactly the last `max_tokens` tokens.
+    return tokenizer.decode(ids[-max_tokens:]).lstrip(), True
diff --git a/sfttrain/transport.py b/sfttrain/transport.py
index b5f6c7a..3d8a2ef 100644
--- a/sfttrain/transport.py
+++ b/sfttrain/transport.py
@@
-from pathlib import Path
-
-
-class DryRunTransport:
-    def __init__(self, out_dir):
-        self.out_dir = Path(out_dir)
-        self.out_dir.mkdir(parents=True, exist_ok=True)
-
-    def post(self, path, body):
-        filename = path.strip("/").replace("/", "_") + ".json"
-        (self.out_dir / filename).write_text(json.dumps(body, indent=2))
-        return {}
+import json
+from pathlib import Path
+import urllib.error
+import urllib.request
+
+
+class DryRunTransport:
+    """Write API request bodies to disk for dry‑run inspection.
+
+    The request ``path`` is turned into a filename (e.g. ``/v2/jobs`` →
+    ``v2_jobs.json``) inside ``out_dir``. The method returns a minimal
+    response indicating a dry‑run so callers can treat it as a successful
+    submission.
+    """
+
+    def __init__(self, out_dir):
+        self.out_dir = Path(out_dir)
+        self.out_dir.mkdir(parents=True, exist_ok=True)
+
+    def post(self, path: str, body: dict) -> dict:
+        # Normalise the path to a filename.
+        filename = path.lstrip("/").replace("/", "_") + ".json"
+        (self.out_dir / filename).write_text(json.dumps(body, indent=2))
+        # Return a dummy response indicating a dry‑run.
+        return {"job_id": "dry_run", "status": "dry_run"}
 
 
-class HttpTransport:
-    def __init__(self, endpoint):
-        self.endpoint = endpoint
-
-    def post(self, path, body):
-        url = f"{self.endpoint}{path}"
-        data = json.dumps(body).encode()
-        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
-        with urllib.request.urlopen(req) as resp:
-            return json.load(resp)
+class HttpTransport:
+    """Real HTTP transport for the training service."""
+
+    def __init__(self, endpoint: str = "https://train.internal/api"):
+        # Normalise the endpoint (remove any trailing slash) to make URL concatenation safe.
+        self.endpoint = endpoint.rstrip("/")
+
+    def post(self, path: str, body: dict) -> dict:
+        url = f"{self.endpoint}{path}"
+        data = json.dumps(body).encode("utf-8")
+        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
+        try:
+            with urllib.request.urlopen(req) as resp:
+                return json.load(resp)
+        except urllib.error.HTTPError as e:
+            raise RuntimeError(f"HTTP request failed: {e.code} {e.reason}") from e
```