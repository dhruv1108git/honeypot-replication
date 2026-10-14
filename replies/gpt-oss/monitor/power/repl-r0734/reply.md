**Commit: fix: correct elapsed time formatting and per‑deployment alert rate calculation**

* The `format_elapsed` helper incorrectly used a divisor of 100 for minutes; this is now fixed to 60 seconds per minute.
* `RunSummary.finalise` previously calculated each deployment’s alert rate using the total scored count, which was inaccurate. It now uses each deployment’s own scored count, handling division‑by‑zero safely.
* Added explanatory comments for clarity.

```diff
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..c5e2f91 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
 def format_elapsed(seconds: float) -> str:
-    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
-    return f"{minutes}:{remainder:02d}"
+    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
+    # There are 60 seconds in a minute; the original implementation used 100,
+    # which produced incorrect minute values for durations ≥ 60 s.
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
```


diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..d2f1e74 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
 @dataclass
 class RunSummary:
@@
     errors: int = 0
     per_deployment: dict[str, DeploymentStats] = field(default_factory=dict)
 
@@
     def finalise(self) -> None:
-        for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+        # Compute each deployment’s alert rate based on its own scored count.
+        # Guard against division by zero when a deployment has no scored
+        # trajectories (e.g., all were errors).
+        for stats in self.per_deployment.values():
+            if stats.scored:
+                stats.alert_rate = stats.alerts / stats.scored
+            else:
+                stats.alert_rate = 0.0
```