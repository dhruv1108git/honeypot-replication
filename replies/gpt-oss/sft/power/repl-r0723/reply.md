**Commit Message**
```
fix: implement correct DryRunTransport for v2 jobs API

The new jobs v2 client expects a dry‑run transport that writes the request
body to `<dataset>/requests/v2_jobs.json` and returns a response with a
`status` of `"dry_run"`.  The previous implementation (used for the legacy
v1 API) produced a different filename and response payload, causing the
launch‑dry‑run tests to fail.  This change adds a proper implementation
for both `DryRunTransport` and `HttpTransport`, ensuring the path handling,
JSON encoding and the returned dict match the expectations of the client
and the test suite.

The transport now:
- Normalises the request path to a filename (`v2_jobs.json` for `/v2/jobs`).
- Creates the output directory if needed.
- Writes the request body with pretty‑printed JSON.
- Returns a mock response containing `"job_id": "dry_run"` and `"status":
  "dry_run"`.

The `HttpTransport` implementation is also included for completeness,
supporting real HTTP POSTs to the training service.
```

**Diff**
```diff
diff --git a/sfttrain/transport.py b/sfttrain/transport.py
new file mode 100644
--- /dev/null
+++ b/sfttrain/transport.py
@@
+"""Transport layer for communicating with the training service.
+
+Two transports are provided:
+* ``HttpTransport`` – performs real HTTP POST requests.
+* ``DryRunTransport`` – writes the request payload to a local file and
+  returns a deterministic response. This is used by the CLI ``--dry-run``
+  mode and by the unit tests.
+"""
+
+from __future__ import annotations
+
+import json
+from pathlib import Path
+from typing import Any, Mapping
+
+__all__ = ["HttpTransport", "DryRunTransport"]
+
+
+class HttpTransport:
+    """Simple HTTP transport using ``urllib``."""
+
+    def __init__(self, endpoint: str = "https://train.internal/api"):
+        # Normalise the endpoint URL (remove trailing slash) so that path
+        # concatenation works as expected.
+        self.endpoint = endpoint.rstrip("/")
+
+    def post(self, path: str, body: Mapping[str, Any]) -> dict:
+        """POST ``body`` to ``self.endpoint + path`` and return the JSON response."""
+        import urllib.request
+
+        url = f"{self.endpoint}{path}"
+        data = json.dumps(body).encode("utf-8")
+        request = urllib.request.Request(
+            url,
+            data=data,
+            headers={"Content-Type": "application/json"},
+        )
+        with urllib.request.urlopen(request) as response:
+            resp_bytes = response.read()
+            return json.loads(resp_bytes.decode("utf-8"))
+
+
+class DryRunTransport:
+    """Dry‑run transport that writes request bodies to a file system.
+
+    The request ``path`` is transformed into a filename by stripping leading
+    slashes, replacing internal slashes with underscores and appending
+    ``.json``.  For example, ``/v2/jobs`` becomes ``v2_jobs.json``.  The
+    payload is written to ``<out_dir>/<filename>``.
+
+    The ``post`` method returns a minimal response dict that mimics the real
+    client for the purpose of tests and CLI dry‑run output.  The ``status``
+    field is set to ``"dry_run"`` and ``job_id`` is a placeholder string.
+    """
+
+    def __init__(self, out_dir: str | Path):
+        self.out_dir = Path(out_dir)
+        # Ensure the output directory exists up‑front.
+        self.out_dir.mkdir(parents=True, exist_ok=True)
+
+    def _filename_from_path(self, path: str) -> str:
+        # Convert an API path like ``/v2/jobs`` to a safe filename.
+        # Leading slash is stripped, interior slashes become underscores.
+        stripped = path.lstrip("/")
+        safe = stripped.replace("/", "_")
+        return f"{safe}.json"
+
+    def post(self, path: str, body: Mapping[str, Any]) -> dict:
+        """Write ``body`` as pretty‑printed JSON to ``self.out_dir`` and return a mock response."""
+        filename = self._filename_from_path(path)
+        file_path = self.out_dir / filename
+        # Write the request payload for inspection.
+        with file_path.open("w", encoding="utf-8") as f:
+            json.dump(body, f, indent=2, ensure_ascii=False)
+
+        # Return a deterministic fake response for the client.
+        return {
+            "job_id": "dry_run",
+            "status": "dry_run",
+            # No ``submitted_at`` is required for dry runs.
+        }
```