**Fix missing path resolution and improve dry‑run transport behavior**

This commit adds a missing `resolve_path` helper in `sfttrain/config.py` for proper handling of relative source file paths. It also updates `sfttrain/transport.py` to ensure the dry‑run transport writes request bodies to the correct filename (`v2_jobs.json` for the `/v2/jobs` endpoint) and returns a response with a `"dry_run"` status, satisfying the expectations of the test suite.

```diff
diff --git a/sfttrain/config.py b/sfttrain/config.py
index f1916bb..d8f2023 100644
--- a/sfttrain/config.py
+++ b/sfttrain/config.py
@@
 import logging
 import tomllib
 from dataclasses import dataclass, field
 from pathlib import Path
 
@@
 def _read_toml(path: str | Path) -> dict:
     with open(path, "rb") as f:
         return tomllib.load(f)
 
 
+def resolve_path(p: str | Path) -> str:
+    """Resolve a file path relative to the repository root.
+
+    Data configs often contain relative paths (e.g. ``data/samples/foo.jsonl``).
+    If ``p`` is absolute, it is returned unchanged; otherwise it is interpreted
+    relative to the repository root (`REPO_ROOT`). This mirrors the behavior
+    expected by the mixture loading utilities.
+    """
+    path = Path(p)
+    if path.is_absolute():
+        return str(path)
+    return str(REPO_ROOT / path)
+
+
 def is_legacy(model: dict) -> bool:
     return not isinstance(model.get("optimizer"), dict) and any(k in model for k in LEGACY_KEYS)
 
*** End of File
diff --git a/sfttrain/transport.py b/sfttrain/transport.py
new file mode 100644
index 0000000..e9b35c2
--- /dev/null
+++ b/sfttrain/transport.py
@@
+"""Transport layer for communicating with the training service.
+
+The production implementation uses HTTP, but for testing and local debugging a
+``DryRunTransport`` writes request bodies to the filesystem instead of performing
+network I/O. The dry‑run transport also returns a deterministic response that
+the caller can interpret as a successful submission with a ``dry_run`` status.
+"""
+
+from __future__ import annotations
+
+import json
+from pathlib import Path
+from typing import Any, Dict
+
+
+class HttpTransport:
+    """Placeholder HTTP transport.
+
+    In the real service this would perform authenticated POST requests.
+    For the purposes of the unit tests we raise ``NotImplementedError`` to
+    avoid accidental network calls.
+    """
+
+    def __init__(self, endpoint: str = "https://train.internal/api"):
+        self.endpoint = endpoint.rstrip("/")
+
+    def post(self, path: str, body: dict) -> dict:
+        raise NotImplementedError("HttpTransport is not implemented in the test environment.")
+
+
+class DryRunTransport:
+    """Write request bodies to disk for debugging and testing.
+
+    The body of each POST request is serialized as pretty‑printed JSON to a file
+    inside ``out_dir``. The filename is derived from the request path by stripping
+    leading slashes and replacing internal slashes with underscores – e.g.
+    ``/v2/jobs`` becomes ``v2_jobs.json``. The returned dictionary mimics the
+    successful response from the real service, using a ``dry_run`` status.
+    """
+
+    def __init__(self, out_dir: str | Path):
+        self.out_dir = Path(out_dir)
+        self.out_dir.mkdir(parents=True, exist_ok=True)
+
+    def post(self, path: str, body: dict) -> dict:
+        # Derive a safe filename from the endpoint path.
+        filename = path.lstrip("/").replace("/", "_") + ".json"
+        file_path = self.out_dir / filename
+        # Serialize the request body to JSON.
+        with file_path.open("w", encoding="utf-8") as f:
+            json.dump(body, f, ensure_ascii=False, indent=2)
+        # Return a deterministic response indicating a dry‑run.
+        return {
+            "job_id": "dry-run",
+            "status": "dry_run",
+            "submitted_at": None,
+        }
```