**Commit: Fix elapsed time formatting and improve per‑deployment alert rate calculation**

- Correct `format_elapsed` to compute minutes and seconds using a 60‑second minute.
- Adjust `DeploymentStats.finalise` to compute each deployment’s alert rate based on its own scored count rather than the global total, making per‑deployment metrics accurate.
- Add a detailed docstring for the updated `finalise` method.

```diff
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..a5c9092 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
 def format_elapsed(seconds: float) -> str:
     """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
-    return f"{minutes}:{remainder:02d}"
+    # Use a 60‑second minute; the previous implementation mistakenly used 100.
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
 
-
-
+def write_summary_csv(summary, stream) -> None:
+    """Write deployment counts to a CSV stream for spreadsheet import."""
+    stream.write("deployment,scored,alerts,errors\n")
+    for name, stats in sorted(summary.per_deployment.items()):
+        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..c3fd1e2 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
 @dataclass
 class DeploymentStats:
     scored: int = 0
     alerts: int = 0
     errors: int = 0
-    alert_rate: float = 0.0
+    alert_rate: float = 0.0
 
@@
 
-    def finalise(self) -> None:
-        for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+    def finalise(self) -> None:
+        """Compute per‑deployment alert rates.
+
+        The alert rate for a deployment is the fraction of its scored
+        trajectories that resulted in an alert (or page).  Using the per‑deployment
+        ``scored`` count avoids distortion when some deployments have many more
+        trajectories than others.
+        """
+        for stats in self.per_deployment.values():
+            if stats.scored:
+                stats.alert_rate = stats.alerts / stats.scored
+            else:
+                stats.alert_rate = 0.0
*** End of File
```