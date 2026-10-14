format_elapsed: use minutes‑seconds conversion correctly  
RunSummary.finalise: compute per‑deployment alert_rate using the deployment’s own counts

```diff
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
-def format_elapsed(seconds: float) -> str:
-    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
-    return f"{minutes}:{remainder:02d}"
+def format_elapsed(seconds: float) -> str:
+    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
+    # The original implementation divided by 100, which produced incorrect
+    # minute values for durations longer than a minute (e.g. 125 s → “1:25”
+    # instead of “2:05”).  Use a 60‑second minute as intended.
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
 
+
 def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
     stream.write("deployment,scored,alerts,errors\n")
@@
 class RunSummary:
@@
     def finalise(self) -> None:
-        for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+        # Compute the alert rate per deployment as alerts divided by the number
+        # of trajectories scored for *that* deployment.  The previous logic
+        # mistakenly used the global run total, which distorted the per‑deployment
+        # metric when deployments had differing numbers of scored trajectories.
+        for stats in self.per_deployment.values():
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```