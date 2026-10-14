commit fix-reporting-and-alerts

Fix runtime formatting and ensure alerts are correctly recorded.

**Changes**
- Correct `format_elapsed` to use 60‑second minutes.
- Extend `AlertSink.record` to insert a row into the `alerts` table for alert or page decisions.
- Preserve existing monitor results insertion and handle `dry_run` mode consistently.

```diff
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..d1f2c9e 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
-def format_elapsed(seconds: float) -> str:
-    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
-    return f"{minutes}:{remainder:02d}"
+def format_elapsed(seconds: float) -> str:
+    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
+    # There are 60 seconds in a minute; the previous implementation mistakenly used 100.
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
 
 def write_summary_csv(summary, stream) -> None:
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
+        """Record the monitoring result and, if warranted, an alert.
+
+        * Always stores the full monitoring result in ``monitor_results``.
+        * If ``decision`` is ``alert`` or ``page`` a row is also inserted into
+          the ``alerts`` table, with ``severity`` set to the decision.
+        """
+        if self.dry_run:
+            return
+        now = _now()
+        # Store the full result for later analysis.
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
+        # If the decision indicates an issue, also record a concrete alert.
+        if decision in ("alert", "page"):
+            self.conn.execute(
+                "INSERT INTO alerts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
+                (
+                    self.run_id,
+                    result.snapshot_id,
+                    result.episode_id,
+                    result.deployment,
+                    result.agent_model,
+                    result.score,
+                    decision,  # severity column
+                    now,
+                ),
+            )
+        if decision == "page" and self.pager is not None:
+            self.pager(result)
```