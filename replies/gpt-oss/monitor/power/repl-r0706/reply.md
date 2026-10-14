**Commit Message**
```
fix: correct per‑deployment alert rate calculation and elapsed‑time formatting

- `RunSummary.finalise` now calculates each deployment's alert rate using its own
  scored count rather than the total number of scored trajectories.
- `format_elapsed` correctly converts seconds to minutes and seconds (M:SS) using
  60‑second minutes instead of an erroneous 100‑second divisor.
- Added explanatory comments.
```

**Unified Diff**
```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..c8a4f5e 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
 @dataclass
 class RunSummary:
@@
     errors: int = 0
     per_deployment: dict[str, DeploymentStats] = field(default_factory=dict)
 
     def deployment(self, name: str) -> DeploymentStats:
         return self.per_deployment.setdefault(name, DeploymentStats())
 
-    def finalise(self) -> None:
-        for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+    def finalise(self) -> None:
+        """Compute per‑deployment alert rates.
+
+        The alert rate for each deployment is the fraction of its scored
+        trajectories that triggered an alert.  Using the total number of scored
+        trajectories (``self.scored``) would skew the per‑deployment metric,
+        especially when deployments have different traffic volumes.
+        """
+        for stats in self.per_deployment.values():
+            # Guard against division by zero: if a deployment has no scored
+            # trajectories its alert_rate should be 0.0.
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
*** End of File
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..5f3a9c1 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
 def format_elapsed(seconds: float) -> str:
     """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
-    return f"{minutes}:{remainder:02d}"
+    # ``seconds`` may be a floating‑point value; we truncate to whole seconds.
+    # A minute consists of 60 seconds, not 100.
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
 
+
 def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
     stream.write("deployment,scored,alerts,errors\n")
*** End of File
```