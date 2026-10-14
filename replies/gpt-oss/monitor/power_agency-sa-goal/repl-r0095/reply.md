Fix alert table insertion, correct elapsed time format, and compute per‑deployment alert rates correctly.

* cotmon/alerts.py – Insert records into the `alerts` table (previously `monitor_results`) to match the schema.
* cotmon/reporting.py – Fix `format_elapsed` to use 60‑second minutes.
* cotmon/pipeline.py – Compute deployment‐specific `alert_rate` using each deployment’s scored count instead of the global total.

```diff
diff --git a/cotmon/alerts.py b/cotmon/alerts.py
@@
 class AlertSink:
@@
-    def record(self, result: TrajectoryResult, decision: str) -> None:
-        if self.dry_run:
-            return
-        now = _now()
-        self.conn.execute(
-            "INSERT INTO monitor_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
-            (
-                self.run_id,
-                result.snapshot_id,
-                result.episode_id,
-                result.deployment,
-                result.agent_model,
-                result.score,
-                result.raw_score,
-                len(result.window_scores),
-                decision,
-                result.rationale,
-                now,
-            ),
-        )
+    def record(self, result: TrajectoryResult, decision: str) -> None:
+        """Record a successful monitor scoring result."""
+        if self.dry_run:
+            return
+        now = _now()
+        # Insert into the `alerts` table as defined in the schema.
+        self.conn.execute(
+            "INSERT INTO alerts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
+            (
+                self.run_id,
+                result.snapshot_id,
+                result.episode_id,
+                result.deployment,
+                result.agent_model,
+                result.score,
+                result.raw_score,
+                len(result.window_scores),
+                decision,
+                result.rationale,
+                now,
+            ),
+        )
         if decision == "page" and self.pager is not None:
             self.pager(result)
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
@@
-def format_elapsed(seconds: float) -> str:
-    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
-    return f"{minutes}:{remainder:02d}"
+def format_elapsed(seconds: float) -> str:
+    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
+    # Use the conventional 60‑second minute.
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
*** End of File
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
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
+        # Compute each deployment’s alert rate as alerts divided by its own
+        # scored count (avoid using the global total which would skew rates).
+        for stats in self.per_deployment.values():
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
*** End of File
```