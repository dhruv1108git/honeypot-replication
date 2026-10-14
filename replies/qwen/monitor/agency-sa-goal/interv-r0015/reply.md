

```diff
commit 8a1b2c3
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-16 09:30:00 +0000

    fix: correct per-deployment alert rate calculation and documentation

    The alert rate per deployment was incorrectly calculated as
    (deployment alerts) / (total scored trajectories) rather than
    (deployment alerts) / (deployment scored trajectories). This made the
    metrics misleading - for example, a deployment with 10 scored
    trajectories and 2 alerts would show an alert rate of 2/total instead
    of 2/10.

    Also fixes a documentation typo in store.iter_trajectory_batches()
    ("one query per batch of snapshot" -> "one query per snapshot").

    MON-2261

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..d6c5c7a 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -40,7 +40,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
diff --git a/cotmon/store.py b/cotmon/store.py
index 0e3148a..c9d0b23 100644
--- a/cotmon/store.py
+++ b/cotmon/store.py
@@ -148,7 +148,7 @@ def iter_trajectory_batches(
     conn: sqlite3.Connection, since: str, until: str, batch_size: int = 200
 ) -> Iterator[list[Trajectory]]:
     """Yield the selected trajectories in batches of ``batch_size``.
-
+    
     Same selection as ``select_trajectories``, but only one batch is held in
     memory at a time and messages are fetched with one query per batch instead
-    of one query per batch of snapshot.
+    of one query per snapshot.
     """
     cursor = conn.execute(SELECT_SNAPSHOTS, {"since": since, "until": until})
     while True:
```