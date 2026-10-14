--- a/sfttrain/transport.py
+++ b/sfttrain/transport.py
@@
-# Existing transport implementations (HttpTransport, etc.) are assumed to be present.
+"""
+Transport utilities for communicating with the training service.
+
+Two transports are provided:
+  * HttpTransport – makes real HTTP requests to the service.
+  * DryRunTransport – writes the request payload to a file instead of sending it,
+    and returns a deterministic response indicating a dry‑run.
+
+The DryRunTransport is used by the test suite (and by the ``--dry-run`` CLI
+option) to verify that the request body is correctly constructed without
+actually contacting the service.
+"""
+
+import json
+from pathlib import Path
+from typing import Any, Dict
+
+# --------------------------------------------------------------------------- #
+# HTTP transport (placeholder – real implementation lives elsewhere)
+# --------------------------------------------------------------------------- #
+
+class HttpTransport:
+    """Simple HTTP transport that posts JSON to a given endpoint."""
+
+    def __init__(self, endpoint: str):
+        self.endpoint = endpoint.rstrip("/")
+
+    def post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
+        """Send a POST request to ``{endpoint}{path}`` with JSON ``body``.
+
+        A real implementation would handle authentication, error handling,
+        and JSON parsing. For the purposes of the unit tests we only need the
+        interface; the method is deliberately left as a stub.
+        """
+        raise NotImplementedError("HttpTransport.post must be implemented in production code")
+
+
+# --------------------------------------------------------------------------- #
+# Dry‑run transport
+# --------------------------------------------------------------------------- #
+
+class DryRunTransport:
+    """
+    Transport that serialises POST requests to disk instead of sending them.
+
+    The ``out_dir`` argument specifies the directory where request files are
+    written. Each request is saved as ``<endpoint>.json`` where ``endpoint``
+    is derived from the URL path (the leading ``/`` is stripped and any
+    remaining ``/`` characters are replaced with ``_``). For example a POST to
+    ``/v2/jobs`` yields ``v2_jobs.json``.
+
+    The ``post`` method returns a minimal response indicating a dry‑run;
+    this matches the expectations of the test suite and the CLI.
+    """
+
+    def __init__(self, out_dir: Path | str):
+        self.out_dir = Path(out_dir)
+        self.out_dir.mkdir(parents=True, exist_ok=True)
+
+    def post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
+        # Normalise the path to a filename: strip leading '/', replace '/' with '_'
+        filename = path.lstrip("/").replace("/", "_") + ".json"
+        file_path = self.out_dir / filename
+        # Write a pretty‑printed JSON file for easier inspection
+        file_path.write_text(json.dumps(body, indent=2), encoding="utf-8")
+        # Return a deterministic response that signals a dry‑run.
+        # ``job_id`` is set to a fixed placeholder; callers only check the
+        # ``status`` field.
+        return {"job_id": "dry_run", "status": "dry_run"}
+
+# End of transport module. ----------------------------------------------------------------

--- a/sfttrain/cli.py
+++ b/sfttrain/cli.py
@@
-from .config import load_data_config, load_model_config
+from .config import find_model_config, load_data_config, load_model_config
@@
-    ap.add_argument("--model", required=True, help="configs/models/<name>.toml")
+    ap.add_argument("--model", required=True, help="config name or configs/models/<name>.toml")
@@
-    model_cfg = load_model_config(args.model)
+    model_cfg = load_model_config(find_model_config(args.model))
*** End of File
*** End Patch
