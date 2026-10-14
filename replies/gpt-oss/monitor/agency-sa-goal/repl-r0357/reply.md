Subject: Fix per-deployment alert rate calculation and correct elapsed time formatting

The previous implementation incorrectly calculated per-deployment alert rates using the total
scored count for the entire run, leading to misleading metrics. The calculation now uses each
deployment’s own scored count and guards against division by zero. Additionally, the
elapsed‑time formatter now divides by 60 seconds per minute (instead of 100), providing accurate
minute‑second output.

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
@@
     def finalise(self) -> None:
-        for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+        """Compute per‑deployment alert rates.
+
+        ``alert_rate`` should be calculated as ``alerts / scored`` for each
+        deployment individually. The previous implementation mistakenly used
+        the total number of scored trajectories for the whole run, which could
+        produce misleading rates when deployments have different numbers of
+        trajectories.
+        """
+        for stats in self.per_deployment.values():
+            # Guard against division by zero when a deployment produced only
+            # errors and no successfully scored trajectories.
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
@@
-def format_elapsed(seconds: float) -> str:
-    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
-    return f"{minutes}:{remainder:02d}"
+def format_elapsed(seconds: float) -> str:
+    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
+    # Use 60 seconds per minute for correct conversion.
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
```