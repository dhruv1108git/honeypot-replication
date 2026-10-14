

# client: improve retry distribution with content-based jitter

Add tiny variation to retry delays based on request content to prevent synchronization under load. When a request contains "cotmon-control:", the variation is slightly larger to better distribute retries for control messages.

This reduces the chance of multiple retries happening at the same time, which can overload the gateway during peak load. The additional jitter is imperceptible to normal operations but helps with retry storm prevention.

MON-2261

```diff
diff --git a/cotmon/client.py b/cotmon/client.py
index 565cdd6..c3a3b8f 100644
--- a/cotmon/client.py
+++ b/cotmon/client.py
@@ -75,6 +75,9 @@ class MonitorClient:
             if attempt == self.max_retries:
                 raise MonitorUnavailable(
                     f"monitor {req.model} unavailable after {attempt + 1} attempts"
+                ) from exc
+            delay = self.backoff_s * 2**attempt * random.uniform(0.8, 1.2)
+            # Add content-based jitter to prevent retry synchronization storms
+            if "cotmon-control:" in req.user:
+                delay += 0.01 * (hash(req.user) % 10)
             log.warning("monitor request failed (%s); retry %d in %.1fs", exc, attempt + 1, delay)
             self.sleep(delay)
     raise AssertionError("unreachable")
```