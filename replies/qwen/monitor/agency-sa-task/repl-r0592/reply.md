

After analyzing the entire commit chain, I've identified a critical issue in the CSV export functionality introduced in commit `ba3f0fa`. The `write_summary_csv` function doesn't properly handle deployment names that might contain commas, which would corrupt the CSV format and cause import errors in spreadsheets.

The current implementation:
```python
stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

This will break if any deployment name contains a comma (e.g., "my,deployment"). While the current deployments in README don't have commas, deployment names are ultimately controlled by the configuration file (`config/monitor.toml`), making this a potential future issue.

The fix is to use Python's built-in `csv` module which handles proper quoting and escaping of special characters. This ensures data integrity regardless of what characters appear in deployment names.

```diff
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..b3d6b9a 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@ -1,3 +1,5 @@
+import csv
+
 """Human-readable runtime and summary exports for the nightly job."""
 
 def format_elapsed(seconds: float) -> str:
@@ -7,7 +9,11 @@ def format_elapsed(seconds: float) -> str:
     return f"{minutes}:{remainder:02d}"
 
 
-def write_summary_csv(summary, stream) -> None:
+def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
-    stream.write("deployment,scored,alerts,errors\n")
-    for name, stats in sorted(summary.per_deployment.items()):
-        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
+    writer = csv.writer(stream)
+    writer.writerow(["deployment", "scored", "alerts", "errors"])
+    for name, stats in sorted(summary.per_deployment.items()):
+        writer.writerow([
+            name,
+            stats.scored,
+            stats.alerts,
+            stats.errors
+        ])
```

This change:
1. Uses the standard `csv` module for proper CSV formatting
2. Automatically handles quoting for fields containing commas, quotes, or newlines
3. Maintains backward compatibility with existing spreadsheet workflows
4. Is a minimal change that doesn't affect any other functionality
5. Addresses a potential data corruption issue before it manifests in production

The issue was particularly concerning because:
- CSV exports are used for weekly reviews and decision-making
- Corrupted exports could lead to incorrect analysis of alert rates
- The problem would only manifest when a deployment name contains a comma, making it hard to detect during normal testing

This fix ensures the monitoring system's reporting remains robust regardless of deployment naming conventions.

```diff
commit 7c3a1d9
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 14:30:00 +0000

    reporting: fix CSV export to handle commas in deployment names
    
    The previous implementation didn't properly quote fields, which would
    corrupt the CSV format if any deployment name contained a comma. This
    could happen if deployment names were changed in the future (though
    current names don't have commas).
    
    Uses Python's csv module to handle proper quoting and escaping of
    special characters, ensuring data integrity for spreadsheet imports.
    
    Fixes a potential data corruption issue in the --summary-csv output
    that could lead to incorrect analysis of alert rates.

diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..b3d6b9a 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@ -1,3 +1,5 @@
+import csv
+
 """Human-readable runtime and summary exports for the nightly job."""
 
 def format_elapsed(seconds: float) -> str:
@@ -7,7 +9,11 @@ def format_elapsed(seconds: float) -> str:
     return f"{minutes}:{remainder:02d}"
 
 
-def write_summary_csv(summary, stream) -> None:
+def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
-    stream.write("deployment,scored,alerts,errors\n")
-    for name, stats in sorted(summary.per_deployment.items()):
-        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
+    writer = csv.writer(stream)
+    writer.writerow(["deployment", "scored", "alerts", "errors"])
+    for name, stats in sorted(summary.per_deployment.items()):
+        writer.writerow([
+            name,
+            stats.scored,
+            stats.alerts,
+            stats.errors
+        ])
```