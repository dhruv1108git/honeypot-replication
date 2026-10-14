Fix elapsed time formatting and per‑deployment alert rate calculation

* Correct `format_elapsed` to use 60‑second minutes instead of 100.
* Compute per‑deployment `alert_rate` using the deployment’s own scored count.
* Add explanatory comments.

```diff
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..e5f1c2a 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
 def format_elapsed(seconds: float) -> str:
     """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
-    return f"{minutes}:{remainder:02d}"
+    # Use 60‑second minutes – the previous implementation mistakenly used 100,
+    # which produced incorrect minute values for durations longer than a minute.
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
 
 
 
 def write_summary_csv(summary, stream) -> None:
@@
 class RunSummary:
@@
     def finalise(self) -> None:
-        for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+        # Compute each deployment's alert rate based on its own scored count.
+        # Previously this used the global `self.scored`, which distorted per‑deployment
+        # metrics when deployments had different numbers of trajectories.
+        for stats in self.per_deployment.values():
+            stats.alert_rate = (
+                stats.alerts / stats.scored if stats.scored else 0.0
+            )
```