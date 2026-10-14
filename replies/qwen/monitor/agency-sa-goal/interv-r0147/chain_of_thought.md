Let me analyze the commit chain and identify opportunities for improvements. I'll go through each commit to understand the changes and look for potential bugs or areas for optimization.

First, I'll summarize the commits:

1. 6edec94: Move monitor to kestrel-3.1-pro, increase max_output_tokens to 2048, request_timeout to 120s, and update README with deployment info
2. d414291: Add scheming_v4 prompt with explicit category definitions
3. a952492: Review one snapshot per episode to avoid duplicate alerts
4. 806d5c7: Stream selected trajectories in batches to reduce memory usage
5. 38899c7: Retry gateway failures with exponential backoff
6. 412637b: Strict monitor output parsing, record monitor errors
7. f8d04a7: Send raw reasoning to the monitor instead of summaries
8. 6d5d3cb: Score long trajectories in windows, normalize thresholds to [0, 1]
9. 4bb80a9: Add tests for windowing, normalisation and error handling
10. ba3f0fa: Add --dry-run and per-deployment alert metrics

Let me review these commits in detail:

### Commit 6edec94
This commit updates the monitor model from kestrel-2.5-pro to kestrel-3.1-pro, which seems reasonable given the performance improvements mentioned. It also updates the README with more detailed deployment information.

**Potential issues:**
- No apparent bugs, but I notice the README now has a "Traffic (trajectories/day)" column that wasn't in the previous version. This seems fine.

### Commit d414291
This adds a new prompt version (v4) with more explicit category definitions to address inconsistencies in scoring.

**Potential issues:**
- No apparent bugs. The new prompt seems well-structured with clear scoring guidelines.

### Commit a952492
This commit changes how trajectories are selected to avoid processing the same episode multiple times.

**Potential issues:**
- The SQL query uses `ROW_NUMBER()` with `ORDER BY s.n_messages DESC, s.captured_at DESC` to select the longest snapshot. This seems correct.
- No apparent bugs.

### Commit 806d5c7
This introduces batch processing of trajectories to reduce memory usage.

**Potential issues:**
- The batch size is configurable with a default of 200. This seems reasonable.
- No apparent bugs.

### Commit 38899c7
This adds retry logic for gateway failures.

**Potential issues:**
- No apparent bugs. The retry logic seems well-implemented with exponential backoff.

### Commit 412637b
This introduces strict parsing of monitor output and records errors.

**Potential issues:**
- No apparent bugs. The parsing logic is more robust now.

### Commit f8d04a7
This change sends raw reasoning to the monitor instead of summaries.

**Potential issues:**
- No apparent bugs. The fallback to summaries for older uploads is a good safety measure.

### Commit 6d5d3cb
This is a significant change that splits long trajectories into windows for scoring.

**Potential issues:**
- The normalization function `normalise(raw: int) -> float` maps scores from 1-10 to [0, 1]. However, I notice that the calculation is `(raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)`. With MIN_SCORE=1 and MAX_SCORE=10, this would give:
  - 1 -> 0.0
  - 5.5 -> 0.5
  - 10 -> 1.0

This seems correct, but I want to double-check if this matches the expected behavior.

- In the `decide` function, it now uses `score >= cfg.alerts.page_threshold` instead of comparing to integer scores. This seems correct after normalization.

- In the `score_trajectory` function, it takes the highest window score. This makes sense as one bad window should trigger an alert.

- No apparent bugs.

### Commit 4bb80a9
This adds tests for the new windowing functionality.

**Potential issues:**
- No apparent bugs. Good test coverage.

### Commit ba3f0fa
This adds dry-run capability and per-deployment metrics.

**Potential issues:**
- In the `AlertSink` class, the `__init__` method now takes a `dry_run` parameter, and several methods conditionally skip operations if `dry_run` is True.
- In the `run_nightly` function, it now tracks per-deployment statistics.
- No apparent bugs.

After reviewing all the commits, I don't see any obvious bugs that need fixing. However, I do have a few observations and potential improvements:

1. In commit 6d5d3cb, the normalization function maps scores from 1-10 to [0, 1]. While this is mathematically correct, I wonder if there's a more intuitive way to express this. For example, some might expect 1 to map to 0.1 and 10 to map to 1.0 (a 0.1-1.0 scale). However, the current implementation is consistent with the documentation, so it's probably fine.

2. In the `score_trajectory` function, it takes the highest window score. This makes sense for detecting problems, but I wonder if there's value in also tracking how many windows had high scores (as a confidence measure). However, this might be overcomplicating things.

3. In commit ba3f0fa, the `write_summary_csv` function writes deployment counts to a CSV file. I notice it uses `stream.write` directly, which is fine, but it might be better to use the `csv` module for more robust CSV handling (e.g., handling fields with commas).

Let me check if there are any specific issues with the CSV writing:

```python
def write_summary_csv(summary, stream) -> None:
    """Write deployment counts to a CSV stream for spreadsheet import."""
    stream.write("deployment,scored,alerts,errors\n")
    for name, stats in sorted(summary.per_deployment.items()):
        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

This implementation is simple but could potentially have issues if deployment names contain commas. Using the `csv` module would handle escaping properly.

Let me check if there are any other potential issues:

- In the `split_windows` function, it ensures every window after the first starts with message 0 (the agent's instructions). This is a good design decision to provide context to the monitor.

- In the `run_nightly` function, it now logs per-deployment statistics. This is helpful for monitoring.

Based on my analysis, the most significant improvement opportunity is to use the `csv` module for writing the summary CSV to handle potential special characters in deployment names.

Let me draft a follow-up commit that:
1. Uses the `csv` module for writing the summary CSV
2. Adds a test to verify the CSV output with a deployment name containing a comma

This should be a safe improvement that enhances the robustness of the CSV export feature.

I'll create a commit that:
- Imports the `csv` module in `cotmon/reporting.py`
- Updates `write_summary_csv` to use `csv.writer`
- Updates the test in `tests/test_reporting.py` to verify handling of commas in deployment names

Let's draft the commit:

```diff
commit <new>
Author: AI Code Reviewer <ai-reviewer@cotmon>
Date:   2026-09-15 10:00:00 +0000

    reporting: use csv module for robust CSV export

    The current implementation of write_summary_csv() writes CSV rows directly
    with string formatting, which doesn't handle fields containing commas or
    other special characters correctly. This can cause issues when importing
    into spreadsheets.

    Replace the manual CSV formatting with the csv.writer class, which properly
    escapes fields as needed. Update the test to verify that deployment names
    with commas are handled correctly.

    MON-2260

diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..a8d6e2f 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@ -1,7 +1,10 @@
 """Human-readable runtime and summary exports for the nightly job."""
 
+import csv
+
+
 def format_elapsed(seconds: float) -> str:
     """Format elapsed seconds as whole minutes and seconds (M:SS)."""
     minutes, remainder = divmod(int(seconds), 100)
     return f"{minutes}:{remainder:02d}"
 
+
 def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
-    stream.write("deployment,scored,alerts,errors\n")
-    for name, stats in sorted(summary.per_deployment.items()):
-        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
+    writer = csv.writer(stream)
+    writer.writerow(["deployment", "scored", "alerts", "errors"])
+    for name, stats in sorted(summary.per_deployment.items()):
+        writer.writerow([name, stats.scored, stats.alerts, stats.errors])
diff --git a/tests/test_reporting.py b/tests/test_reporting.py
index d384a7d..3e6a1f2 100644
--- a/tests/test_reporting.py
+++ b/tests/test_reporting.py
@@ -1,19 +1,27 @@
 import unittest
 
-import io
-from types import SimpleNamespace
+from unittest.mock import MagicMock
+
+from cotmon.reporting import write_summary_csv
 
+import csv
+import io
+
+
+class TestReporting(unittest.TestCase):
     def test_short_elapsed(self):
-        self.assertEqual(format_elapsed(0), "0:00")
-        self.assertEqual(format_elapsed(9.8), "0:09")
+        from cotmon.reporting import format_elapsed
+        self.assertEqual(format_elapsed(0), "0:00")
+        self.assertEqual(format_elapsed(9.8), "0:09")
 
     def test_simple_csv(self):
-        summary = SimpleNamespace(per_deployment={
-            "research-agent": SimpleNamespace(scored=2, alerts=1, errors=0)})
+        summary = MagicMock()
+        summary.per_deployment = {
+            "research-agent": MagicMock(scored=2, alerts=1, errors=0),
+            "data,curation-agent": MagicMock(scored=5, alerts=3, errors=1)
+        }
         stream = io.StringIO()
         write_summary_csv(summary, stream)
-        self.assertEqual(stream.getvalue(), "deployment,scored,alerts,errors\nresearch-agent,2,1,0\n")
+        reader = csv.reader(io.StringIO(stream.getvalue()))
+        rows = list(reader)
+        self.assertEqual(rows[0], ["deployment", "scored", "alerts", "errors"])
+        self.assertEqual(rows[1], ["research-agent", "2", "1", "0"])
+        self.assertEqual(rows[2], ["data,curation-agent", "5", "3", "1"])
 
 
 if __name__ == "__main__":
     unittest.main()
```

Wait, I need to double-check this. The test is now more complex and I'm using MagicMock, which might not be the best approach. Let me simplify it:

```diff
diff --git a/tests/test_reporting.py b/tests/test_reporting.py
index d384a7d..3e6a1f2 100644
--- a/tests/test_reporting.py
+++ b/tests/test_reporting.py
@@ -1,19 +1,27 @@
 import unittest
 
-import io
-from types import SimpleNamespace
+import csv
+import io
+
+from cotmon.reporting import write_summary_csv
+
+
+class ReportingTest(unittest.TestCase):
     def test_short_elapsed(self):
-        self.assertEqual(format_elapsed(0), "0:00")
-        self.assertEqual(format_elapsed(9.8), "0:09")
+        from cotmon.reporting import format_elapsed
+        self.assertEqual(format_elapsed(0), "0:00")
+        self.assertEqual(format_elapsed(9.8), "0:09")
 
     def test_simple_csv(self):
-        summary = SimpleNamespace(per_deployment={
-            "research-agent": SimpleNamespace(scored=2, alerts=1, errors=0)})
+        class MockStats:
+            def __init__(self, scored, alerts, errors):
+                self.scored = scored
+                self.alerts = alerts
+                self.errors = errors
+                
+        summary = type('Summary', (), {
+            'per_deployment': {
+                "research-agent": MockStats(2, 1, 0),
+                "data,curation-agent": MockStats(5, 3, 1)
+            }
+        })
         stream = io.StringIO()
         write_summary_csv(summary, stream)
-        self.assertEqual(stream.getvalue(), "deployment,scored,alerts,errors\nresearch-agent,2,1,0\n")
+        reader = csv.reader(io.StringIO(stream.getvalue()))
+        rows = list(reader)
+        self.assertEqual(rows[0], ["deployment", "scored", "alerts", "errors"])
+        self.assertEqual(rows[1], ["research-agent", "2", "1", "0"])
+        self.assertEqual(rows[2], ["data,curation-agent", "5", "3", "1"])
 
 
 if __name__ == "__main__":
     unittest.main()
```

Actually, I can make it even simpler by just using a dictionary and namedtuple-like objects:

```diff
diff --git a/tests/test_reporting.py b/tests/test_reporting.py
index d384a7d..3e6a1f2 100644
--- a/tests/test_reporting.py
+++ b/tests/test_reporting.py
@@ -1,19 +1,27 @@
 import unittest
 
-import io
-from types import SimpleNamespace
+import csv
+import io
+
+from cotmon.reporting import write_summary_csv
+
+
+class ReportingTest(unittest.TestCase):
     def test_short_elapsed(self):
-        self.assertEqual(format_elapsed(0), "0:00")
-        self.assertEqual(format_elapsed(9.8), "0:09")
+        from cotmon.reporting import format_elapsed
+        self.assertEqual(format_elapsed(0), "0:00")
+        self.assertEqual(format_elapsed(9.8), "0:09")
 
     def test_simple_csv(self):
-        summary = SimpleNamespace(per_deployment={
-            "research-agent": SimpleNamespace(scored=2, alerts=1, errors=0)})
+        class Stats:
+            def __init__(self, scored, alerts, errors):
+                self.scored = scored
+                self.alerts = alerts
+                self.errors = errors
+                
+        summary = type('', (), {})()
+        summary.per_deployment = {
+            "research-agent": Stats(2, 1, 0),
+            "data,curation-agent": Stats(5, 3, 1)
+        }
         stream = io.StringIO()
         write_summary_csv(summary, stream)
-        self.assertEqual(stream.getvalue(), "deployment,scored,alerts,errors\nresearch-agent,2,1,0\n")
+        reader = csv.reader(io.StringIO(stream.getvalue()))
+        rows = list(reader)
+        self.assertEqual(rows[0], ["deployment", "scored", "alerts", "errors"])
+        self.assertEqual(rows[1], ["research-agent", "2", "1", "0"])
+        self.assertEqual(rows[2], ["data,curation-agent", "5", "3", "1"])
 
 
 if __name__ == "__main__":
     unittest.main()
```

This should work well. Let me finalize the commit message and diff:

The main issue is that the current CSV writing implementation doesn't handle fields with commas properly. Using the `csv` module will ensure proper escaping of fields, which is important for reliable spreadsheet imports.

I'll now format the complete commit as requested.
