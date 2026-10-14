config/fix‑elapsed‑format‑and‑alert‑rate

Fix elapsed time formatting to use minutes based on 60 seconds and correct per‑deployment alert rate calculation.

- `cotmon/reporting.py`: change `format_elapsed` divisor from 100 to 60 for proper minute/second conversion.
- `cotmon/pipeline.py`: compute each deployment's `alert_rate` using its own `scored` count, guarding against division by zero.

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
+    # One minute equals 60 seconds. Use integer division for minutes and the
+    # remainder for seconds to produce a human‑readable duration.
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
*** End of File
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
     def finalise(self) -> None:
-        for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+        # Compute each deployment's alert rate based on its own scored count.
+        # Guard against division by zero in case a deployment produced no scores.
+        for stats in self.per_deployment.values():
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
*** End of File
```