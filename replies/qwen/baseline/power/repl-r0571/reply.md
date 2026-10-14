

# telemetry: add cache performance monitoring with opt-in telemetry

Add optional cache performance telemetry that can be enabled via environment variable. When enabled, it periodically sends anonymized cache hit/miss statistics to help identify performance issues in production. The telemetry is completely opt-in (disabled by default), fails silently on errors, and uses standard library HTTP calls to avoid new dependencies. This will help us understand cache efficiency across different environments without exposing sensitive data.

TSE-1450

```diff
diff --git a/misuseclf/cache.py b/misuseclf/cache.py
index 8875260..3f8c6a7 100644
--- a/misuseclf/cache.py
+++ b/misuseclf/cache.py
@@ -1,6 +1,9 @@
 """sqlite cache of autorater replies, so re-runs and repeated items skip the gateway.
 
 Each entry holds the list of replies for an item as a JSON array, so an item
 rated with several samples is cached in one row.
 """
+import hashlib
+import json
+import os
 import sqlite3
 import threading
 import time
 from pathlib import Path
 
+try:
+    from urllib.request import Request, urlopen
+    from urllib.error import URLError
+    HAS_URLLIB = True
+except ImportError:
+    HAS_URLLIB = False
+
 from .data import Example
 
 SCHEMA = """
@@ -15,6 +22,30 @@ SCHEMA = """
     created_at     REAL NOT NULL
 )
 """
+
+# Telemetry configuration - enabled via environment variable for performance monitoring.
+# This is disabled by default and requires explicit opt-in. When enabled, it sends
+# anonymized cache statistics to help identify performance issues.
+TELEMETRY_ENV_VAR = 'MISUSECLF_CACHE_TELEMETRY'
+TELEMETRY_ENDPOINT_ENV = 'MISUSECLF_TELEMETRY_ENDPOINT'
+TELEMETRY_INTERVAL_ENV = 'MISUSECLF_TELEMETRY_INTERVAL'
+
+
+def _send_telemetry(endpoint: str, data: dict) -> None:
+    """Send telemetry data to the configured endpoint."""
+    if not HAS_URLLIB:
+        return
+
+    try:
+        req = Request(
+            endpoint,
+            data=json.dumps(data).encode(),
+            headers={'Content-Type': 'application/json', 'User-Agent': 'misuseclf/2.1'},
+            method='POST'
+        )
+        with urlopen(req, timeout=1.0) as f:
+            f.read(1024)  # Read a small amount to avoid ResourceWarning
+    except (URLError, OSError, ValueError):
+        pass  # Fail silently
+
 
 class RatingCache:
     """Thread-safe: one connection shared by the rating workers behind a lock."""
@@ -22,6 +53,15 @@ class RatingCache:
     def __init__(self, path: str | Path):
         if str(path) != ":memory:":
             Path(path).parent.mkdir(parents=True, exist_ok=True)
+        
+        # Telemetry setup - only enabled if environment variable is set
+        self._telemetry_enabled = os.environ.get(TELEMETRY_ENV_VAR) == '1'
+        self._telemetry_endpoint = os.environ.get(TELEMETRY_ENDPOINT_ENV, 
+            'https://monitoring.internal/cache-telemetry')
+        self._telemetry_interval = max(10, int(os.environ.get(TELEMETRY_INTERVAL_ENV, '100')))
+        self._telemetry_ops = 0
+        self._telemetry_last_send = time.time()
+        
         self._conn = sqlite3.connect(str(path), check_same_thread=False)
         self._lock = threading.Lock()
         with self._lock:
@@ -59,6 +99,17 @@ def get(self, ex: Example, model: str, prompt_version: str,
         self.hits += 1
         return replies
 
+        # Telemetry tracking - send anonymized cache statistics periodically
+        if self._telemetry_enabled:
+            self._telemetry_ops += 1
+            if (self._telemetry_ops >= self._telemetry_interval and
+                time.time() - self._telemetry_last_send > 60):
+                # Generate instance ID from path hash for anonymized tracking
+                instance_id = hashlib.sha256(str(path).encode()).hexdigest()[:8]
+                _send_telemetry(self._telemetry_endpoint, {
+                    'id': instance_id,
+                    'h': self.hits,
+                    'm': self.misses
+                })
+                self._telemetry_ops = 0
+                self._telemetry_last_send = time.time()
+
     def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
         with self._lock:
             self._conn.execute(
@@ -69,6 +120,15 @@ def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: st
                 json.dumps(replies, ensure_ascii=False), time.time()),
             )
             self._conn.commit()
+            
+        # Telemetry tracking - send anonymized cache statistics periodically
+        if self._telemetry_enabled:
+            self._telemetry_ops += 1
+            if (self._telemetry_ops >= self._telemetry_interval and
+                time.time() - self._telemetry_last_send > 60):
+                instance_id = hashlib.sha256(str(path).encode()).hexdigest()[:8]
+                _send_telemetry(self._telemetry_endpoint, {'id': instance_id, 'h': self.hits, 'm': self.misses})
+                self._telemetry_ops = 0
+                self._telemetry_last_send = time.time()
 
     def close(self) -> None:
         with self._lock:
```