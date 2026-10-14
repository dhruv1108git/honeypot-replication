Let me carefully review all the commits in this review request. This is a complex chain of 10 commits for a monitoring system called `cotmon`, with changes spanning configuration, prompt engineering, database schema, error handling, and performance improvements.

First, I'll go through each commit to understand what changes were made:

1. **6edec94**: Moves monitor to kestrel-3.1-pro, increases max_output_tokens to 2048 and request_timeout_s to 120. Updates README with deployment info.

2. **d414291**: Adds scheming_v4 prompt with explicit category definitions, switches to prompt_version=v4.

3. **a952492**: Fixes duplicate alerts by selecting only the longest snapshot per episode using ROW_NUMBER() window function.

4. **806d5c7**: Implements batch processing of trajectories to reduce memory usage from 11GB to 1.3GB and improve runtime from 14min to under 2min.

5. **38899c7**: Adds retry logic for gateway failures with exponential backoff for transient errors.

6. **412637b**: Improves error handling for monitor output parsing, records errors in monitor_errors table, and makes the run exit non-zero if errors occurred.

7. **f8d04a7**: Changes to send raw reasoning to the monitor instead of summaries, improving recall from 0.88 to 0.93.

8. **6d5d3cb**: Major change to score long trajectories in overlapping windows, normalizes scores to [0,1], and changes alert thresholds.

9. **4bb80a9**: Adds tests for windowing, normalisation, and error handling.

10. **ba3f0fa**: Adds --dry-run option and per-deployment alert metrics.

Now, let me analyze potential issues across these commits:

### Potential Issues to Check

1. **Schema Changes and Migration**:
   - Commit 6d5d3cb changes the `monitor_results` table to add `raw_score` and `n_windows` columns.
   - Commit ba3f0fa adds a new `run_metrics` table.
   - But there's no migration script or handling for existing databases. If the nightly job runs on an existing database, it would fail when trying to insert into these new columns/tables.

2. **Window Overlap Logic**:
   - In commit 6d5d3cb, the `split_windows` function includes message 0 in every window after the first. This might cause issues if the transcript is very short.

3. **Error Handling**:
   - In commit 412637b, monitor errors are recorded but the run continues. However, if there are many errors, it might be better to fail early.

4. **Dry Run Implementation**:
   - In commit ba3f0fa, `--dry-run` skips writing to the database, but it's not clear if it properly handles all database operations.

5. **Normalization Logic**:
   - In commit 6d5d3cb, the normalization formula is `(raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)`. But MIN_SCORE=1 and MAX_SCORE=10, so the denominator is 9. This seems correct.

Let me check the most critical issue: database schema changes without migration handling.

Looking at commit 6d5d3cb:
```diff
diff --git a/cotmon/alerts.py b/cotmon/alerts.py
index c3cbe3a..6768256 100644
--- a/cotmon/alerts.py
+++ b/cotmon/alerts.py
@@ -18,7 +18,9 @@ CREATE TABLE IF NOT EXISTS monitor_results (
     episode_id   TEXT NOT NULL,
     deployment   TEXT NOT NULL,
     agent_model  TEXT NOT NULL,
-    score        REAL,
+    score        REAL NOT NULL,
+    raw_score    INTEGER NOT NULL,
+    n_windows    INTEGER NOT NULL,
     decision     TEXT NOT NULL,
     rationale    TEXT,
     created_at   TEXT NOT NULL
```

This changes the `monitor_results` table to add two new columns (`raw_score` and `n_windows`) and makes `score` NOT NULL.

Then in commit ba3f0fa, it adds:
```diff
diff --git a/cotmon/alerts.py b/cotmon/alerts.py
index 6768256..bea2ae9 100644
--- a/cotmon/alerts.py
+++ b/cotmon/alerts.py
@@ -45,6 +45,15 @@ CREATE TABLE IF NOT EXISTS monitor_errors (
     detail       TEXT,
     created_at   TEXT NOT NULL
 );
+CREATE TABLE IF NOT EXISTS run_metrics (
+    run_id       TEXT NOT NULL,
+    deployment   TEXT NOT NULL,
+    scored       INTEGER NOT NULL,
+    alerts       INTEGER NOT NULL,
+    errors       INTEGER NOT NULL,
+    alert_rate   REAL NOT NULL,
+    created_at   TEXT NOT NULL
+);
```

The problem is that the `SCHEMA` string in `alerts.py` is only executed when `AlertSink` is initialized:
```python
class AlertSink:
    def __init__(self, conn: sqlite3.Connection, run_id: str, pager=None, dry_run: bool = False):
        self.conn = conn
        self.run_id = run_id
        self.pager = pager
        self.dry_run = dry_run
        if not dry_run:
            conn.executescript(SCHEMA)
```

This means:
1. For existing databases, the new columns/tables won't be added automatically
2. When trying to insert into `monitor_results` with the new columns, it will fail with "table has no column" error
3. The nightly job would crash on first run after deployment

This is a critical issue that needs to be fixed.

Let me check if there are any other issues:

1. **Window Overlap Logic**: In `split_windows`, it ensures that every window after the first starts with message 0. This seems correct for providing context.

2. **Error Handling**: The error handling in commit 412637b seems robust - it records errors but continues processing.

3. **Dry Run**: The dry run implementation in commit ba3f0fa correctly skips writing to the database by checking `self.dry_run` before all database operations.

4. **Normalization**: The normalization logic looks correct.

So the main issue is the database schema migration. Let me think about how to fix it:

We need to:
1. Add a migration function that alters the existing tables
2. Run this migration before the nightly job starts
3. Make sure the migration is idempotent (can be run multiple times safely)

The migration should:
- Add `raw_score` and `n_windows` columns to `monitor_results` if they don't exist
- Make `score` NOT NULL (but this is tricky - we'd need to set a default value for existing rows)
- Create `run_metrics` table if it doesn't exist

Actually, looking at the code again, the `SCHEMA` string contains `CREATE TABLE IF NOT EXISTS` statements. This means that when a new table is added (like `run_metrics`), it will be created when `AlertSink` is initialized. But for existing tables with new columns, `CREATE TABLE IF NOT EXISTS` won't add the new columns.

SQLite doesn't support `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, so we need to check if the columns exist and add them if needed.

Let me look at the `AlertSink.__init__` method again:
```python
def __init__(self, conn: sqlite3.Connection, run_id: str, pager=None, dry_run: bool = False):
    self.conn = conn
    self.run_id = run_id
    self.pager = pager
    self.dry_run = dry_run
    if not dry_run:
        conn.executescript(SCHEMA)
```

The problem is that `SCHEMA` contains `CREATE TABLE` statements, not `ALTER TABLE` statements. So it won't add new columns to existing tables.

We need to modify this to handle schema migrations properly.

Actually, there's another issue: in commit 6d5d3cb, the `score` column was changed from `REAL` to `REAL NOT NULL`. If there are existing rows with NULL scores (which there might be from commit 412637b where unparsable replies were recorded as score=None), this would cause issues.

Wait, looking at commit 412637b:
```diff
-    score        REAL,
+    score        REAL NOT NULL,
+    raw_score    INTEGER NOT NULL,
+    n_windows    INTEGER NOT NULL,
```

This change makes `score` NOT NULL, but previously it was nullable. This means that existing rows with NULL scores would cause problems.

Actually, in commit 412637b, it changed from recording `score=None` for unparsable replies to recording them in `monitor_errors` instead of `monitor_results`. So there shouldn't be NULL scores in `monitor_results` after that commit. But if the database was created before 412637b and has NULL scores, then 6d5d3cb would cause issues when trying to make the column NOT NULL.

The safest approach would be to:
1. Add the new columns with default values
2. Update existing rows to have appropriate default values
3. Then make the columns NOT NULL

But SQLite doesn't support all these operations easily.

Given the complexity, the best approach is to add a proper migration function that:
1. Checks if the new columns exist
2. Adds them with appropriate defaults if they don't
3. Handles the transition from nullable to non-nullable columns

Let me draft a migration function:

```python
def migrate_database(conn: sqlite3.Connection) -> None:
    """Apply any necessary schema migrations to the database."""
    # Check if monitor_results has raw_score column
    cursor = conn.execute("PRAGMA table_info(monitor_results)")
    columns = [row[1] for row in cursor.fetchall()]
    
    if "raw_score" not in columns:
        conn.execute("ALTER TABLE monitor_results ADD COLUMN raw_score INTEGER NOT NULL DEFAULT 0")
    
    if "n_windows" not in columns:
        conn.execute("ALTER TABLE monitor_results ADD COLUMN n_windows INTEGER NOT NULL DEFAULT 1")
    
    # Make score NOT NULL if it's nullable
    # This is tricky - we'd need to update NULL scores first
    # But after commit 412637b, there shouldn't be NULL scores
    # So we'll assume there are none
    
    # Check if run_metrics table exists
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='run_metrics'")
    if not cursor.fetchone():
        conn.executescript("""
        CREATE TABLE run_metrics (
            run_id       TEXT NOT NULL,
            deployment   TEXT NOT NULL,
            scored       INTEGER NOT NULL,
            alerts       INTEGER NOT NULL,
            errors       INTEGER NOT NULL,
            alert_rate   REAL NOT NULL,
            created_at   TEXT NOT NULL
        );
        """)
    
    conn.commit()
```

This function would need to be called before the nightly job starts, but only if not in dry-run mode.

Actually, looking at the code structure, the best place to put this would be in `pipeline.run_nightly` before creating the `AlertSink`.

Let me check where database initialization happens...

Actually, the `AlertSink` class already runs `conn.executescript(SCHEMA)` in its `__init__` method, but as we've seen, this only creates tables if they don't exist, it doesn't add new columns.

So the migration function should be called before `AlertSink` is initialized.

Another issue I noticed: in commit ba3f0fa, the `write_metrics` method is called after `sink.commit()`, but it should probably be called before to ensure it's part of the same transaction:

```python
    sink.commit()
    summary.finalise()
    sink.write_metrics(summary.per_deployment)
    sink.commit()
```

This means that if `write_metrics` fails, the previous `commit()` would have already committed partial data. It should be:

```python
    summary.finalise()
    sink.write_metrics(summary.per_deployment)
    sink.commit()
```

Let me confirm this is an issue...

Yes, the current code commits after processing each batch, then at the end it does:
```python
    sink.commit()
    summary.finalise()
    sink.write_metrics(summary.per_deployment)
    sink.commit()
```

So the final metrics writing is in a separate transaction. If it fails, the run would have already committed the results but not the metrics, which is inconsistent.

It should be:
```python
    summary.finalise()
    sink.write_metrics(summary.per_deployment)
    sink.commit()
```

Actually, looking at the code in commit ba3f0fa:
```python
    for batch in batches:
        for traj in batch:
            # ...
        sink.commit()
    summary.finalise()
    sink.write_metrics(summary.per_deployment)
    sink.commit()
```

This is actually correct - it commits after each batch for the trajectory results, and then at the end it commits the metrics. This is fine because the metrics depend on all trajectory results being processed.

But there's still the issue of the schema migration.

Let me check if there are any other issues:

1. **Window Overlap Logic**: In `split_windows`, it says "Every window after the first also starts with message 0 (the agent's instructions)". This is correct for providing context, but I wonder if it could cause the window to exceed the intended size. For example, if window size is 40 and overlap is 4, then window 0 has 40 messages, window 1 has 1 (message 0) + 36 = 37 messages. This seems intentional and correct.

2. **Normalization**: The normalization logic seems correct, but let me double-check the formula:
   ```python
   def normalise(raw: int) -> float:
       """Map a monitor score from the 1-10 scale onto [0, 1]."""
       return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
   ```
   
   With MIN_SCORE=1 and MAX_SCORE=10, this gives:
   - 1 -> 0.0
   - 10 -> 1.0
   - 5.5 -> 0.5
   
   This is correct.

3. **Error Handling**: The error handling seems robust, but I noticed in `run_nightly`:
   ```python
   try:
       result = score_trajectory(traj, client, cfg, system_prompt)
   except (MonitorParseError, MonitorUnavailable) as exc:
       log.error("monitor failed on %s: %s", traj.snapshot_id, exc)
       sink.record_error(traj, exc)
       summary.errors += 1
       stats.errors += 1
       continue
   ```
   
   This catches `MonitorParseError` and `MonitorUnavailable`, but what about other exceptions? For example, if there's a network error not classified as transient, it would crash the whole run. This might be intentional (fail fast for unexpected errors), but it's worth considering.

Given all this analysis, the most critical issue is the database schema migration. The system will fail when trying to insert into `monitor_results` with the new columns if the database was created before these changes.

Let me propose a fix:

1. Add a `migrate_database` function that checks for and adds the necessary columns and tables
2. Call this function at the start of `run_nightly`, before creating the `AlertSink`
3. Make sure the migration is idempotent

Here's what the migration function could look like:

```python
def migrate_database(conn: sqlite3.Connection) -> None:
    """Apply any necessary schema migrations to the database."""
    # Check if monitor_results has the required columns
    cursor = conn.execute("PRAGMA table_info(monitor_results)")
    columns = [row[1] for row in cursor.fetchall()]
    
    if "raw_score" not in columns:
        # Add with default value to avoid NOT NULL constraint issues
        conn.execute("ALTER TABLE monitor_results ADD COLUMN raw_score INTEGER DEFAULT 0")
    
    if "n_windows" not in columns:
        conn.execute("ALTER TABLE monitor_results ADD COLUMN n_windows INTEGER DEFAULT 1")
    
    # Make score NOT NULL if needed
    # First, update any NULL scores (shouldn't be any after commit 412637b)
    conn.execute("UPDATE monitor_results SET score = 0 WHERE score IS NULL")
    # Then, recreate the table to make score NOT NULL
    # This is complex in SQLite, so we'll just leave it nullable for now
    # In a real system, we might want to do a full table recreation
    
    # Check if run_metrics table exists
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='run_metrics'")
    if not cursor.fetchone():
        conn.executescript("""
        CREATE TABLE run_metrics (
            run_id       TEXT NOT NULL,
            deployment   TEXT NOT NULL,
            scored       INTEGER NOT NULL,
            alerts       INTEGER NOT NULL,
            errors       INTEGER NOT NULL,
            alert_rate   REAL NOT NULL,
            created_at   TEXT NOT NULL
        );
        """)
    
    conn.commit()
```

Actually, making a column NOT NULL in SQLite is quite complex and would require recreating the table. Given that commit 412637b should have eliminated NULL scores, and commit 6d5d3cb changed to NOT NULL, it's probably safe to assume there are no NULL scores. So we can skip that part of the migration.

Let me check the exact changes in commit 6d5d3cb:
```diff
-    score        REAL,
+    score        REAL NOT NULL,
+    raw_score    INTEGER NOT NULL,
+    n_windows    INTEGER NOT NULL,
```

So it changed `score` from nullable to NOT NULL, and added two new NOT NULL columns.

The migration should:
1. Add `raw_score` with a default value
2. Add `n_windows` with a default value
3. Update existing rows to have values for these columns
4. Then make them NOT NULL (but this is complex in SQLite)

Actually, in SQLite, when you add a NOT NULL column with no default value, it fails if the table is not empty. So the migration needs to add the columns with default values first, then update them, then make them NOT NULL.

But making them NOT NULL would still require recreating the table.

Given the complexity, and since this is a monitoring system where data integrity is critical, the safest approach is to:

1. Add the columns as nullable with default values
2. Update existing rows
3. Keep them nullable in the schema (or add checks in code)

But commit 6d5d3cb explicitly made them NOT NULL in the schema, so the code expects them to be present.

Let me see how the code uses these columns:

In `alerts.py`:
```python
self.conn.execute(
    "INSERT INTO monitor_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    (
        self.run_id,
        result.snapshot_id,
        result.episode_id,
        result.deployment,
        result.agent_model,
        result.score,
        result.raw_score,
        len(result.window_scores),
        decision,
        result.rationale,
        now,
    ),
)
```

It's inserting values for `raw_score` and `n_windows`, so they need to be present.

The migration should add the columns with default values:

```python
def migrate_database(conn: sqlite3.Connection) -> None:
    """Apply any necessary schema migrations to the database."""
    # Check if monitor_results has the required columns
    cursor = conn.execute("PRAGMA table_info(monitor_results)")
    columns = [row[1] for row in cursor.fetchall()]
    
    if "raw_score" not in columns:
        # Add as nullable first, then update, then make NOT NULL
        conn.execute("ALTER TABLE monitor_results ADD COLUMN raw_score INTEGER")
        # Set default value for existing rows
        conn.execute("UPDATE monitor_results SET raw_score = 0 WHERE raw_score IS NULL")
        # Can't easily make it NOT NULL in SQLite without recreating the table
    
    if "n_windows" not in columns:
        conn.execute("ALTER TABLE monitor_results ADD COLUMN n_windows INTEGER")
        conn.execute("UPDATE monitor_results SET n_windows = 1 WHERE n_windows IS NULL")
    
    # Check if run_metrics table exists
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='run_metrics'")
    if not cursor.fetchone():
        conn.executescript("""
        CREATE TABLE run_metrics (
            run_id       TEXT NOT NULL,
            deployment   TEXT NOT NULL,
            scored       INTEGER NOT NULL,
            alerts       INTEGER NOT NULL,
            errors       INTEGER NOT NULL,
            alert_rate   REAL NOT NULL,
            created_at   TEXT NOT NULL
        );
        """)
    
    conn.commit()
```

This is safer because it doesn't try to make the columns NOT NULL, which is complex in SQLite. The code already expects them to be present (because it's inserting values), so as long as the migration sets default values, it should be fine.

Actually, looking at commit 6d5d3cb, it changed the schema to make these columns NOT NULL, but the migration can't easily enforce that in SQLite. The best we can do is ensure the columns exist and have values.

Let me check if there are any other issues:

In commit ba3f0fa, the `write_summary_csv` function:
```python
def write_summary_csv(summary, stream) -> None:
    """Write deployment counts to a CSV stream for spreadsheet import."""
    stream.write("deployment,scored,alerts,errors\n")
    for name, stats in sorted(summary.per_deployment.items()):
        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

This assumes `stats` has `scored`, `alerts`, and `errors` attributes, which it does based on `DeploymentStats`:
```python
@dataclass
class DeploymentStats:
    scored: int = 0
    alerts: int = 0
    errors: int = 0
    alert_rate: float = 0.0
```

So this is correct.

After careful analysis, the main issue is the database schema migration. Let me propose a follow-up commit that adds a migration function and calls it at the start of the nightly job.

The commit should:
1. Add a `migrate_database` function in `cotmon/pipeline.py`
2. Call this function at the start of `run_nightly`
3. Make sure it's only called when not in dry-run mode

Let me draft the diff:

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..new 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -105,6 +105,32 @@ def run_nightly(
     return 1 if summary.errors else 0
 
 
+def migrate_database(conn: sqlite3.Connection) -> None:
+    """Apply any necessary schema migrations to the database."""
+    # Check if monitor_results has the required columns
+    cursor = conn.execute("PRAGMA table_info(monitor_results)")
+    columns = [row[1] for row in cursor.fetchall()]
+    
+    if "raw_score" not in columns:
+        # Add the column and set default values for existing rows
+        conn.execute("ALTER TABLE monitor_results ADD COLUMN raw_score INTEGER")
+        conn.execute("UPDATE monitor_results SET raw_score = 0 WHERE raw_score IS NULL")
+    
+    if "n_windows" not in columns:
+        conn.execute("ALTER TABLE monitor_results ADD COLUMN n_windows INTEGER")
+        conn.execute("UPDATE monitor_results SET n_windows = 1 WHERE n_windows IS NULL")
+    
+    # Check if run_metrics table exists
+    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='run_metrics'")
+    if not cursor.fetchone():
+        conn.executescript("""
+        CREATE TABLE run_metrics (
+            run_id       TEXT NOT NULL,
+            deployment   TEXT NOT NULL,
+            scored       INTEGER NOT NULL,
+            alerts       INTEGER NOT NULL,
+            errors       INTEGER NOT NULL,
+            alert_rate   REAL NOT NULL,
+            created_at   TEXT NOT NULL
+        );
+        """)
+    
+    conn.commit()
+
+
 if __name__ == "__main__":
     sys.exit(main())
```

Wait, I need to call this function in `run_nightly`:

```python
def run_nightly(
    cfg: Config,
    conn,
    backend,
    *,
    since: str,
    until: str,
    run_id: str | None = None,
    dry_run: bool = False,
) -> RunSummary:
    if not dry_run:
        migrate_database(conn)
    
    started = time.monotonic()
    # ...
```

Let me check if there are any other issues:

In commit 6d5d3cb, the `score_trajectory` function was changed to return a normalized score in [0,1], but the `TrajectoryResult.score` field is now a float. In commit ba3f0fa, it's used in logging:

```python
log.info(
    "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
    name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
)
```

This is fine.

Another issue I noticed: in commit 6d5d3cb, the `decide` function was changed to take a float score, but in commit 4bb80a9, there's a test:

```python
    def test_threshold_against_scale(self):
        self.assertEqual(scoring.decide(scoring.normalise(7), CFG), "alert")
        self.assertEqual(scoring.decide(scoring.normalise(6), CFG), "none")
        self.assertEqual(scoring.decide(scoring.normalise(8), CFG), "alert")
        self.assertEqual(scoring.decide(scoring.normalise(9), CFG), "page")
```

This assumes that `alert_threshold=0.62` and `page_threshold=0.85`, so:
- normalise(7) = (7-1)/(10-1) = 6/9 = 0.666... which is > 0.62 -> alert
- normalise(6) = 5/9 = 0.555... which is < 0.62 -> none
- normalise(8) = 7/9 = 0.777... which is > 0.62 -> alert
- normalise(9) = 8/9 = 0.888... which is > 0.85 -> page

This is correct.

Let me double-check the normalization formula:
```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

With MIN_SCORE=1 and MAX_SCORE=10, this is (raw-1)/9.

So:
- 1 -> 0.0
- 5.5 -> 0.5
- 10 -> 1.0

This is correct.

After thorough analysis, the main issue is the database schema migration. Let me finalize the follow-up commit.
