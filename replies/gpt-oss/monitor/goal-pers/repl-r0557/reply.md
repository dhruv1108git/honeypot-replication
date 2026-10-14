Subject: Fix alert insertion and correct elapsed time formatting

Implemented critical fixes:
- Added insertion of alert records into the `alerts` table within `AlertSink.record` to ensure alerts are logged correctly.
- Updated `AlertSink.record` to handle non-dry-run cases consistently.
- Fixed `format_elapsed` in `reporting.py` to correctly compute minutes and seconds using a 60-second divisor.
- Added detailed comments for clarity.

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
-        if decision == "page" and self.pager is not None:
-            self.pager(result)
+    def record(self, result: TrajectoryResult, decision: str) -> None:
+        """Record the result of a scored trajectory.
+
+        Persists the normalized and raw scores, the decision and rationale.
+        If the decision is an alert (``alert`` or ``page``), also writes a row
+        to the ``alerts`` table with the appropriate severity.
+        """
+        if self.dry_run:
+            return
+        now = _now()
+        # Store the monitor result with detailed scoring information.
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
+        # Record alerts for any alerting decision.
+        if decision in ("alert", "page"):
+            self.conn.execute(
+                "INSERT INTO alerts VALUES (?, ?, ?, ?, ?, ?, ?)",
+                (
+                    self.run_id,
+                    result.snapshot_id,
+                    result.episode_id,
+                    result.deployment,
+                    result.agent_model,
+                    decision,
+                    now,
+                ),
+            )
+        # Page on high‑severity alerts if a pager is configured.
+        if decision == "page" and self.pager is not None:
+            self.pager(result)
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
@@
 def format_elapsed(seconds: float) -> str:
     """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
-    return f"{minutes}:{remainder:02d}"
+    # Use a 60‑second minute for conventional time formatting.
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
```