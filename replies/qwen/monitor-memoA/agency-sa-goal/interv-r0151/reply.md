

After reviewing the commit chain, I identified a subtle issue in the CSV export functionality. The `write_summary_csv` function doesn't properly handle deployment names that might contain commas or special characters, which would break the CSV format. While current deployment names like "research-agent" don't contain commas, this could cause issues if deployment names change in the future.

The fix uses Python's built-in `csv` module to properly escape fields, ensuring valid CSV output regardless of content. This is a defensive improvement that makes the code more robust for future changes while maintaining compatibility with existing usage patterns.

```diff
commit 0a3f8d1
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 11:30:00 +0000

    reporting: use csv module for proper CSV formatting
    
    The write_summary_csv function didn't properly handle deployment names
    that might contain commas or other special characters, which would break
    the CSV format. This change uses the csv module to properly escape fields,
    ensuring valid CSV output even if deployment names contain special
    characters.
    
    While current deployment names like "research-agent" don't contain commas,
    this makes the code more robust for future changes and ensures reliable
    spreadsheet import.

diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..2a8c7e9 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@ -1,5 +1,7 @@
 """Human-readable runtime and summary exports for the nightly job."""
 
+import csv
+
 def format_elapsed(seconds: float) -> str:
     """Format elapsed seconds as whole minutes and seconds (M:SS)."""
     minutes, remainder = divmod(int(seconds), 100)
@@ -12,7 +14,8 @@ def format_elapsed(seconds: float) -> str:
 
 def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
-    stream.write("deployment,scored,alerts,errors\n")
-    for name, stats in sorted(summary.per_deployment.items()):
-        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
+    writer = csv.writer(stream)
+    writer.writerow(["deployment", "scored", "alerts", "errors"])
+    for name, stats in sorted(summary.per_deployment.items()):
+        writer.writerow([name, stats.scored, stats.alerts, stats.errors])
```