commit 9f6b2c1 – Fix: insert alerts into alerts table and correct elapsed time formatting

Subject: Fix: insert alerts into alerts table and correct elapsed time formatting

This update addresses two issues uncovered by the test suite:
1. **Alerts Table Population** – Previously, scored trajectories were only recorded in `monitor_results`, leaving the `alerts` table empty. Tests expecting entries in `alerts` (e.g., `test_alert_written`) now succeed as we insert a row into `alerts` whenever a trajectory triggers an alert or page decision.
2. **Elapsed Time Formatting** – The `format_elapsed` utility incorrectly used a 100‑second minute divisor, causing mis‑formatted runtime logs. It now correctly divides by 60 to produce standard `M:SS` output.

Additional enhancements:
- Updated `cotmon/alerts.py` to perform the dual insertion (both `monitor_results` and `alerts`).
- Adjusted `format_elapsed` in `cotmon/reporting.py` to use a 60‑second base.
- Included comprehensive documentation comments for clarity.

These changes restore expected functionality, improve logging accuracy, and maintain alignment with the monitoring platform’s alert tracking requirements.

```diff
diff --git a/cotmon/alerts.py b/cotmon/alerts.py
@@
 class AlertSink:
@@
-    def record(self, result: TrajectoryResult, decision: str) -> None:
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
-        if decision == "page" and self.pager is not None:
-            self.pager(result)
+    def record(self, result: TrajectoryResult, decision: str) -> None:
+        """Record a scored trajectory.
+
+        Stores a detailed row in ``monitor_results`` and, for any alert or
+        page decision, also records a summary entry in the ``alerts`` table.
+        """
+        now = _now()
+        # Detailed monitor result (always recorded).
+        self.conn.execute(
+            "INSERT INTO monitor_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
+        # Summary alerts table: store only when an alert or page is triggered.
+        if decision in ("alert", "page"):
+            self.conn.execute(
+                "INSERT INTO alerts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
+                (
+                    self.run_id,
+                    result.snapshot_id,
+                    result.episode_id,
+                    result.deployment,
+                    result.agent_model,
+                    result.raw_score,
+                    decision,
+                    result.rationale,
+                    now,
+                ),
+            )
+        if decision == "page" and self.pager is not None:
+            self.pager(result)
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
@@
-def format_elapsed(seconds: float) -> str:
-    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
-    return f"{minutes}:{remainder:02d}"
+def format_elapsed(seconds: float) -> str:
+    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
+    # Use a 60‑second minute to produce conventional M:SS output.
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
```