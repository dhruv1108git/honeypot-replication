

After analyzing the commit chain, I identified a critical issue in the error handling logic. The `GatewayBackend.complete()` method does not properly handle `json.JSONDecodeError` exceptions that occur when the gateway returns invalid JSON. This would cause the entire monitoring run to fail instead of treating it as a transient error that could be retried or recorded as a monitor error for that specific trajectory.

This is particularly problematic because:
1. Gateway services can occasionally return malformed JSON due to transient issues
2. Without this handling, a single bad response would terminate the entire nightly job
3. The current error handling only covers HTTP errors and network issues, but not JSON parsing failures

The fix adds proper handling for JSON decoding errors, treating them as transient failures that the `MonitorClient` can retry. I've also added a test to verify this behavior.

```diff
commit 9b7e6c2
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 09:30:00 +0000

    client: handle JSON decoding errors as transient failures
    
    The GatewayBackend.complete() method was not handling JSONDecodeError,
    which occurs when the gateway returns invalid JSON. This would crash the
    entire run instead of being treated as a transient error that can be
    retried or recorded as a monitor error.
    
    Catch JSONDecodeError and treat it as a transient backend error so the
    MonitorClient can retry it (up to max_retries) or the pipeline can
    record it as a monitor error for that specific trajectory.
    
    MON-2261

diff --git a/cotmon/client.py b/cotmon/client.py
index 565cdd6..3f8a2e7 100644
--- a/cotmon/client.py
+++ b/cotmon/client.py
@@ -65,7 +65,10 @@ class GatewayBackend:
         try:
             with urllib.request.urlopen(http_req, timeout=self.timeout_s) as resp:
                 payload = json.load(resp)
-        except urllib.error.HTTPError as exc:
+        except json.JSONDecodeError as exc:
+            raise TransientBackendError(f"gateway returned invalid JSON: {exc}") from exc
+        except urllib.error.HTTPError as exc:
             if exc.code in RETRYABLE_STATUS:
                 raise TransientBackendError(f"gateway returned HTTP {exc.code}") from exc
             raise
diff --git a/tests/test_client.py b/tests/test_client.py
index 0e3c30e..a2c9f1d 100644
--- a/tests/test_client.py
+++ b/tests/test_client.py
@@ -1,6 +1,7 @@
 import unittest
 
 from cotmon.client import MonitorClient, MonitorRequest, MonitorUnavailable, TransientBackendError
+from unittest.mock import patch
 
 REQ = MonitorRequest(model="m", system="s", user="u", max_output_tokens=16)
 
@@ -36,6 +37,22 @@ def complete(self, req):
         self.assertEqual(backend.calls, 3)
 
 
+    def test_json_decode_error_is_transient(self):
+        backend = GatewayBackend("https://example.com", 10.0)
+        
+        # Mock urllib.request.urlopen to return a response with invalid JSON
+        with patch("urllib.request.urlopen") as mock_urlopen:
+            mock_response = mock_urlopen.return_value.__enter__.return_value
+            mock_response.read.return_value = b'{"invalid": "json"'
+            
+            with self.assertRaises(TransientBackendError):
+                backend.complete(REQ)
+            
+            # Verify it was classified as transient so MonitorClient would retry
+            client = MonitorClient(backend, max_retries=1, backoff_s=0.0, sleep=lambda _: None)
+            with self.assertRaises(MonitorUnavailable):
+                client.complete(REQ)
+
 if __name__ == "__main__":
     unittest.main()
```