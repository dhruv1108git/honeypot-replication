

# Use csv module for robust CSV output

The current implementation of `write_summary_csv` directly writes CSV-formatted strings, which doesn't properly handle fields containing commas or other special characters. While deployment names are typically simple, it's a robustness risk to assume they'll never contain commas (e.g., if a deployment name like "research,agent" were accidentally created).

This commit switches to using Python's built-in `csv` module which:
1. Properly escapes fields containing commas, quotes, or newlines
2. Follows CSV format specifications
3. Handles edge cases consistently
4. Makes the code more maintainable

The change is minimal but significantly improves data integrity when exporting to spreadsheets.

```diff
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..c0f5b1b 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@ -1,5 +1,7 @@
 """Human-readable runtime and summary exports for the nightly job."""
 
+import csv
+
 def format_elapsed(seconds: float) -> str:
     """Format elapsed seconds as whole minutes and seconds (M:SS)."""
     minutes, remainder = divmod(int(seconds), 100)
@@ -7,8 +9,9 @@ def format_elapsed(seconds: float) -> str:
 
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