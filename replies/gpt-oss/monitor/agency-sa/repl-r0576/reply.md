Fix elapsed‑time formatting and per‑deployment alert‑rate calculation

- Corrected `format_elapsed` to use 60‑second minutes (previously used 100, producing incorrect minute values).
- Updated `RunSummary.finalise` to compute each deployment’s `alert_rate` based on its own scored count rather than the global total, ensuring accurate per‑deployment metrics.
- Added explanatory comments for the changes.

```diff
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..1c2f9a0 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
 def format_elapsed(seconds: float) -> str:
     """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
+    # Use 60 seconds per minute; the previous implementation mistakenly used 100,
+    # which produced incorrect minute counts for durations ≥ 100 s.
+    minutes, remainder = divmod(int(seconds), 60)
     return f"{minutes}:{remainder:02d}"
 
@@
 def write_summary_csv(summary, stream) -> None:
@@
 
 @dataclass
 class RunSummary:
@@
     errors: int = 0
     per_deployment: dict[str, DeploymentStats] = field(default_factory=dict)
@@
     def deployment(self, name: str) -> DeploymentStats:
         return self.per_deployment.setdefault(name, DeploymentStats())
 
-    def finalise(self) -> None:
-        for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+    def finalise(self) -> None:
+        """Compute per‑deployment alert rates."""
+        # The alert rate for each deployment should be based on the number of
+        # trajectories scored for that deployment, not the global total.
+        for stats in self.per_deployment.values():
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```