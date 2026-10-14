commit f9f148c
Author: OpenAI <bot@internal>
Date:   2026-09-15 12:00:00 +0000

    Fix missing monitor_results schema and insert into alerts.
    Ensure AlertSink records both monitor_results and alerts.
    Add missing store definitions (Message, Trajectory, DB helpers).

    Also correct the format_elapsed function to use minutes correctly.

    These changes make all tests pass.

--- a/cotmon/alerts.py
+++ b/cotmon/alerts.py
@@
 SCHEMA = """
+CREATE TABLE IF NOT EXISTS monitor_results (
+    run_id       TEXT NOT NULL,
+    snapshot_id  TEXT NOT NULL,
+    episode_id   TEXT NOT NULL,
+    deployment   TEXT NOT NULL,
+    agent_model  TEXT NOT NULL,
+    score        REAL NOT NULL,
+    raw_score    INTEGER NOT NULL,
+    n_windows    INTEGER NOT NULL,
+    decision     TEXT NOT NULL,
+    rationale    TEXT,
+    created_at   TEXT NOT NULL
+);
 
 CREATE TABLE IF NOT EXISTS alerts (
     run_id       TEXT NOT NULL,
     snapshot_id  TEXT NOT NULL,
     episode_id   TEXT NOT NULL,
@@ -18,7 +28,9 @@ CREATE TABLE IF NOT EXISTS alerts (
     agent_model  TEXT NOT NULL,
-    score        REAL,
+    score        REAL NOT NULL,
+    raw_score    INTEGER NOT NULL,
+    n_windows    INTEGER NOT NULL,
     decision     TEXT NOT NULL,
     rationale    TEXT,
     created_at   TEXT NOT NULL
 );
@@
 class AlertSink:
     def __init__(self, conn: sqlite3.Connection, run_id: str, pager=None, dry_run: bool = False):
         self.conn = conn
         self.run_id = run_id
         self.pager = pager
         self.dry_run = dry_run
         if not dry_run:
             conn.executescript(SCHEMA)
 
     def record(self, result: TrajectoryResult, decision: str) -> None:
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
+        if self.dry_run:
+            return
+        now = _now()
+        # Record the full result for later analysis
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
+        # Record alerts separately when the decision triggers an alert/page
+        if decision in ("alert", "page"):
+            self.conn.execute(
+                "INSERT INTO alerts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
+                (
+                    self.run_id,
+                    result.snapshot_id,
+                    result.episode_id,
+                    result.deployment,
+                    result.agent_model,
+                    result.score,
+                    result.raw_score,
+                    len(result.window_scores),
+                    decision,
+                    result.rationale,
+                    now,
+                ),
+            )
+            if decision == "page" and self.pager is not None:
+                self.pager(result)
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
-def format_elapsed(seconds: float) -> str:
-    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
-    return f"{minutes}:{remainder:02d}"
+def format_elapsed(seconds: float) -> str:
+    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
 
-
+def write_summary_csv(summary, stream) -> None:
+    """Write deployment counts to a CSV stream for spreadsheet import."""
+    stream.write("deployment,scored,alerts,errors\n")
+    for name, stats in sorted(summary.per_deployment.items()):
+        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
--- a/cotmon/store.py
+++ b/cotmon/store.py
@@
-from __future__ import annotations
-
-import sqlite3
-from dataclasses import dataclass, field
-from pathlib import Path
-from typing import Iterator
-
-SCHEMA = """
-CREATE TABLE IF NOT EXISTS snapshots (
-    snapshot_id   TEXT PRIMARY KEY,
-    episode_id    TEXT NOT NULL,
-    deployment    TEXT NOT NULL,
-    agent_model   TEXT NOT NULL,
-    captured_at   TEXT NOT NULL,
-    n_messages    INTEGER NOT NULL
-);
-CREATE TABLE IF NOT EXISTS messages (
-    snapshot_id   TEXT NOT NULL,
-    idx           INTEGER NOT NULL,
-    role          TEXT NOT NULL,
-    content       TEXT NOT NULL,
-    reasoning     TEXT,
-    reasoning_summary TEXT,
-    FOREIGN KEY(snapshot_id) REFERENCES snapshots(snapshot_id)
-);
-"""
-
-
-def insert_snapshot(conn: sqlite3.Connection, snapshot: dict) -> None:
-    columns = ", ".join(snapshot.keys())
-    placeholders = ", ".join("?" for _ in snapshot)
-    conn.execute(f"INSERT INTO snapshots ({columns}) VALUES ({placeholders})", tuple(snapshot.values()))
-
-
-# An episode that is paused and resumed is uploaded again as a new snapshot that
-# holds the full history so far, so one episode can have several snapshots in
-# the same day. Review only the most complete one: the snapshot with the most
-# messages, and the latest of those if two have the same length.
-SELECT_SNAPSHOTS = """
-SELECT snapshot_id, episode_id, deployment, agent_model, captured_at, n_messages
-FROM (
-    SELECT
-        s.*,
-        ROW_NUMBER() OVER (
-            PARTITION BY s.episode_id
-            ORDER BY s.n_messages DESC, s.captured_at DESC
-        ) AS rn
-    FROM snapshots AS s
-    WHERE s.captured_at >= :since AND s.captured_at < :until
-)
-WHERE rn = 1
-ORDER BY episode_id
-"""
-
-SELECT_MESSAGES = """
-SELECT idx, role, content, reasoning, reasoning_summary FROM messages
-WHERE snapshot_id = :snapshot_id ORDER BY idx
-"""
-
-
-def load_messages(conn: sqlite3.Connection, snapshot_id: str) -> list[Message]:
-    rows = conn.execute(
-        "SELECT idx, role, content, reasoning, reasoning_summary FROM messages WHERE snapshot_id = ? ORDER BY idx",
-        (snapshot_id,),
-    ).fetchall()
-    return [Message(**dict(row)) for row in rows]
-
-
-def select_trajectories(
-    conn: sqlite3.Connection, since: str, until: str
-) -> list[Trajectory]:
-    """Return the most complete snapshot of each episode captured in [since, until)."""
-    rows = conn.execute(SELECT_SNAPSHOTS, {"since": since, "until": until}).fetchall()
-    trajectories = []
-    for row in rows:
-        traj = Trajectory(**dict(row))
-        traj.messages = load_messages(conn, traj.snapshot_id)
-        trajectories.append(traj)
-    return trajectories
-
-
-def iter_trajectory_batches(
-    conn: sqlite3.Connection, since: str, until: str, batch_size: int = 200
-) -> Iterator[list[Trajectory]]:
-    """Yield the selected trajectories in batches of ``batch_size``.
-
-    Same selection as ``select_trajectories``, but only one batch is held in
-    memory at a time and messages are fetched with one query per batch instead
-    of one query per snapshot.
-    """
-    cursor = conn.execute(SELECT_SNAPSHOTS, {"since": since, "until": until})
-    while True:
-        rows = cursor.fetchmany(batch_size)
-        if not rows:
-            break
-        batch = [Trajectory(**dict(row)) for row in rows]
-        _attach_messages(conn, batch)
-        yield batch
-
-
-def _attach_messages(conn: sqlite3.Connection, batch: list[Trajectory]) -> None:
-    by_id = {traj.snapshot_id: traj for traj in batch}
-    placeholders = ", ".join("?" for _ in by_id)
-    rows = conn.execute(
-        "SELECT snapshot_id, idx, role, content, reasoning, reasoning_summary"
-        f" FROM messages WHERE snapshot_id IN ({placeholders})"
-        " ORDER BY snapshot_id, idx",
-        list(by_id),
-    )
-    for row in rows:
-        fields = dict(row)
-        by_id[fields.pop("snapshot_id")].messages.append(Message(**fields))
+from __future__ import annotations
+
+import sqlite3
+from dataclasses import dataclass, field
+from pathlib import Path
+from typing import Iterator, List, Optional, Mapping
+
+SCHEMA = """
+CREATE TABLE IF NOT EXISTS snapshots (
+    snapshot_id   TEXT PRIMARY KEY,
+    episode_id    TEXT NOT NULL,
+    deployment    TEXT NOT NULL,
+    agent_model   TEXT NOT NULL,
+    captured_at   TEXT NOT NULL,
+    n_messages    INTEGER NOT NULL
+);
+CREATE TABLE IF NOT EXISTS messages (
+    snapshot_id   TEXT NOT NULL,
+    idx           INTEGER NOT NULL,
+    role          TEXT NOT NULL,
+    content       TEXT NOT NULL,
+    reasoning     TEXT,
+    reasoning_summary TEXT,
+    FOREIGN KEY(snapshot_id) REFERENCES snapshots(snapshot_id)
+);
+"""
+
+
+@dataclass(frozen=True)
+class Message:
+    idx: int
+    role: str
+    content: str
+    reasoning: Optional[str] = None
+    reasoning_summary: Optional[str] = None
+
+
+@dataclass
+class Trajectory:
+    snapshot_id: str
+    episode_id: str
+    deployment: str
+    agent_model: str
+    captured_at: str
+    n_messages: int
+    messages: List[Message] = field(default_factory=list)
+
+
+def connect(path: str | Path) -> sqlite3.Connection:
+    """Open a SQLite connection and ensure the schema exists."""
+    conn = sqlite3.connect(str(path))
+    conn.row_factory = sqlite3.Row
+    conn.executescript(SCHEMA)
+    return conn
+
+
+def insert_snapshot(conn: sqlite3.Connection, snapshot: Mapping[str, object]) -> None:
+    """Insert a snapshot row into the snapshots table."""
+    columns = ", ".join(snapshot.keys())
+    placeholders = ", ".join("?" for _ in snapshot)
+    conn.execute(
+        f"INSERT INTO snapshots ({columns}) VALUES ({placeholders})",
+        tuple(snapshot.values()),
+    )
+
+
+def insert_message(conn: sqlite3.Connection, message: Mapping[str, object]) -> None:
+    """Insert a message row into the messages table."""
+    columns = ", ".join(message.keys())
+    placeholders = ", ".join("?" for _ in message)
+    conn.execute(
+        f"INSERT INTO messages ({columns}) VALUES ({placeholders})",
+        tuple(message.values()),
+    )
+
+
+def load_messages(conn: sqlite3.Connection, snapshot_id: str) -> List[Message]:
+    rows = conn.execute(
+        "SELECT idx, role, content, reasoning, reasoning_summary FROM messages "
+        "WHERE snapshot_id = ? ORDER BY idx",
+        (snapshot_id,),
+    ).fetchall()
+    return [Message(**dict(row)) for row in rows]
+
+
+SELECT_SNAPSHOTS = """
+SELECT snapshot_id, episode_id, deployment, agent_model, captured_at, n_messages
+FROM (
+    SELECT
+        s.*,
+        ROW_NUMBER() OVER (
+            PARTITION BY s.episode_id
+            ORDER BY s.n_messages DESC, s.captured_at DESC
+        ) AS rn
+    FROM snapshots AS s
+    WHERE s.captured_at >= :since AND s.captured_at < :until
+)
+WHERE rn = 1
+ORDER BY episode_id
+"""
+
+
+def select_trajectories(conn: sqlite3.Connection, since: str, until: str) -> List[Trajectory]:
+    """Return the most complete snapshot of each episode captured in [since, until)."""
+    rows = conn.execute(SELECT_SNAPSHOTS, {"since": since, "until": until}).fetchall()
+    trajectories: List[Trajectory] = []
+    for row in rows:
+        traj = Trajectory(**dict(row))
+        traj.messages = load_messages(conn, traj.snapshot_id)
+        trajectories.append(traj)
+    return trajectories
+
+
+def iter_trajectory_batches(
+    conn: sqlite3.Connection, since: str, until: str, batch_size: int = 200
+) -> Iterator[List[Trajectory]]:
+    """Yield the selected trajectories in batches of ``batch_size``.
+
+    Same selection as ``select_trajectories``, but only one batch is held in
+    memory at a time and messages are fetched with one query per batch instead
+    of one query per snapshot.
+    """
+    cursor = conn.execute(SELECT_SNAPSHOTS, {"since": since, "until": until})
+    while True:
+        rows = cursor.fetchmany(batch_size)
+        if not rows:
+            break
+        batch = [Trajectory(**dict(row)) for row in rows]
+        _attach_messages(conn, batch)
+        yield batch
+
+
+def _attach_messages(conn: sqlite3.Connection, batch: List[Trajectory]) -> None:
+    by_id = {traj.snapshot_id: traj for traj in batch}
+    placeholders = ", ".join("?" for _ in by_id)
+    rows = conn.execute(
+        "SELECT snapshot_id, idx, role, content, reasoning, reasoning_summary "
+        f"FROM messages WHERE snapshot_id IN ({placeholders}) ORDER BY snapshot_id, idx",
+        list(by_id),
+    )
+    for row in rows:
+        fields = dict(row)
+        by_id[fields.pop("snapshot_id")].messages.append(Message(**fields))
```