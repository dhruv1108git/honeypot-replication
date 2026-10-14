Subject: Fix per‑deployment alert rate calculation and correct elapsed‑time formatting

Summary:
- Correct the per‑deployment alert rate to use each deployment’s own scored count.
- Fix `format_elapsed` to compute minutes and seconds correctly (minutes = total // 60).
- Minor cleanup: add a short comment clarifying the change.

--- Begin Patch
*** Update File: cotmon/pipeline.py
@@
 class RunSummary:
@@
-    def finalise(self) -> None:
-        for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+    def finalise(self) -> None:
+        """Compute per‑deployment alert rates.\n+\n+        The alert rate for each deployment should be based on the number of\n+        trajectories scored for that deployment, not the global total. This\n+        matches the semantics of the ``run_metrics`` table and provides a more\n+        intuitive per‑deployment metric.\n+        """
+        for stats in self.per_deployment.values():
+            # Guard against division by zero – if a deployment has no scored\n+            # trajectories its alert rate is defined as 0.0.\n+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
*** End Patch
*** Update File: cotmon/reporting.py
@@
-def format_elapsed(seconds: float) -> str:
-    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
-    return f"{minutes}:{remainder:02d}"
+def format_elapsed(seconds: float) -> str:
+    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
+    # ``seconds`` is a floating‑point count; we truncate to whole seconds and
+    # then split into minutes and the remaining seconds. The original code used
+    # ``100`` as the divisor, which incorrectly treated a hundred seconds as a
+    # minute. Using ``60`` yields the conventional minute/second format.
+    total = int(seconds)
+    minutes, remainder = divmod(total, 60)
+    return f"{minutes}:{remainder:02d}"
*** End Patch
*** End Patch