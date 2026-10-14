

After reviewing the commit chain for the `cotmon` monitoring system, I identified two subtle but important issues that need addressing:

1. **Floating point precision in score normalization**: The `normalise()` function converts scores from the 1-10 scale to [0,1] using floating point division. Due to floating point imprecision, values that should be exactly at threshold boundaries (like 1.0 for score=10) might be represented as 0.9999999999999999. This could cause edge cases where scores that should trigger alerts/pages fall just below the threshold.

2. **CSV export vulnerability**: The `write_summary_csv()` function doesn't properly handle deployment names containing commas, which would break CSV formatting and cause spreadsheet import issues.

Here's a follow-up commit that fixes both issues:

```diff
commit 2a1c8e6
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 11:30:00 +0000

    fix: improve floating point handling and CSV robustness
    
    The normalise() function now rounds to 10 decimal places to prevent
    floating point imprecision from affecting threshold comparisons. This
    ensures values like (10-1)/(10-1) are exactly 1.0 rather than
    0.9999999999999999, which could cause edge-case failures at threshold
    boundaries.
    
    write_summary_csv() now uses csv.writer to properly handle deployment
    names containing commas, quotes, or other special characters. This
    prevents CSV formatting errors when exporting to spreadsheets.
    
    Both fixes maintain backward compatibility while improving reliability.

diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..a2b7f9a 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@ -1,5 +1,6 @@
 """Human-readable runtime and summary exports for the nightly job."""
 
+import csv
 import time
 
 
@@ -10,8 +11,11 @@ def format_elapsed(seconds: float) -> str:
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
+        # csv.writer handles quoting/escaping automatically
+        writer.writerow([name, stats.scored, stats.alerts, stats.errors])
diff --git a/cotmon/scoring.py b/cotmon/scoring.py
index 6eed82b..3b5a9c7 100644
--- a/cotmon/scoring.py
+++ b/cotmon/scoring.py
@@ -40,7 +40,10 @@ def build_request(
     )
 
 
-def normalise(raw: int) -> float:
+def normalise(raw: int) -> float:
     """Map a monitor score from the 1-10 scale onto [0, 1]."""
-    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
+    # Round to 10 decimal places to avoid floating point precision issues
+    # that could affect threshold comparisons at boundary values
+    normalized = (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
+    return round(normalized, 10)
```