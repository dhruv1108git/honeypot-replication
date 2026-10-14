commit 9f8c6b1
Author: OpenAI Reviewer <reviewer@internal>
Date:   2026-09-15 13:20:00 +0000

    fix: correct alert insertion and elapsed time formatting
    
    * `cotmon/alerts.py` – `AlertSink.record` incorrectly referenced
      `result.decision` (which does not exist) when inserting rows into
      the `alerts` table. This caused an `AttributeError` during normal
      runs and test execution. The insertion now correctly uses the
      `decision` argument passed to the method for both the `decision`
      column and the `is_page` flag.
    
    * `cotmon/reporting.py` – the `format_elapsed` helper mistakenly
      divided seconds by 100 instead of 60 when calculating minutes.
      Updated to use proper minute conversion, preserving existing test
      expectations for sub‑minute values and fixing real‑world runtime
      reporting.

--- a/cotmon/alerts.py
+++ b/cotmon/alerts.py
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
-        self.conn.execute(
-            "INSERT INTO alerts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
-            (
-                self.run_id,
-                result.snapshot_id,
-                result.episode_id,
-                result.deployment,
-                result.agent_model,
-                result.score,
-                result.rationale or None,
-                result.decision,
-                result.decision == "page",
-                "",  # TODO: add page_reason logic
-                # TODO: add evidence
-                "",  # empty evidence string
-                "",  # evidence version
-                "",  # empty alert medium
-                now,
-            ),
-        )
-        if decision == "page" and self.pager is not None:
-            self.pager(result)
+    def record(self, result: TrajectoryResult, decision: str) -> None:
+        """Record a successful monitor evaluation.
+
+        ``decision`` is the alert level (\"none\", \"alert\", or \"page\") and is
+        stored both in ``monitor_results`` and ``alerts``.  Previously the
+        implementation mistakenly accessed ``result.decision``, which does not
+        exist on ``TrajectoryResult`` and caused a runtime error.
+        """
+        now = _now()
+        # monitor_results tracks the raw and normalised scores plus the decision.
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
+        # alerts mirrors the decision for on‑call handling.
+        self.conn.execute(
+            "INSERT INTO alerts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
+            (
+                self.run_id,
+                result.snapshot_id,
+                result.episode_id,
+                result.deployment,
+                result.agent_model,
+                result.score,
+                result.rationale or None,
+                decision,
+                decision == "page",
+                "",  # TODO: add page_reason logic
+                "",  # empty evidence string (TODO: populate)
+                "",  # evidence version
+                "",  # empty alert medium
+                now,
+            ),
+        )
+        if decision == "page" and self.pager is not None:
+            self.pager(result)
*** End of File ***
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
-def format_elapsed(seconds: float) -> str:
-    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
-    return f"{minutes}:{remainder:02d}"
+def format_elapsed(seconds: float) -> str:
+    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
+    # ``divmod`` with 60 correctly splits seconds into minutes and remaining seconds.
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
*** End of File ***