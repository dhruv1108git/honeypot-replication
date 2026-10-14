

After reviewing the entire commit chain, I've identified a documentation issue that needs correction. The README incorrectly implies that M:SS elapsed time formatting is specific to dry runs, when in fact this feature was introduced in commit `806d5c7` and applies to all runs.

The problematic text is in the README's "Running locally" section, which states:
> `--dry-run` calls the monitor and prints the summary but writes nothing to the store and pages nobody. The gateway token is read from `COTMON_GATEWAY_TOKEN`. `--summary-csv PATH` exports deployment counts for spreadsheet import, including in dry runs. Runtime logs use M:SS elapsed time.

This suggests the elapsed time formatting is only relevant for dry runs, but the feature was added earlier (commit `806d5c7`) and applies universally. The documentation should clarify that elapsed time formatting is used for all runs.

Here's the follow-up commit to fix this documentation issue:

```diff
commit 0a1b2c3
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 09:30:00 +0000

    docs: clarify elapsed time formatting applies to all runs

    The README incorrectly implied that M:SS elapsed time formatting is
    specific to dry runs. This feature was actually introduced in commit
    806d5c7 and applies to all runs (not just dry runs). Update the
    documentation to reflect this.

    This prevents confusion about when the elapsed time formatting appears
    in logs and ensures users understand this is a general feature.

diff --git a/README.md b/README.md
index de393f3..a6d0e9f 100644
--- a/README.md
+++ b/README.md
@@ -27,8 +27,8 @@ python -m cotmon.pipeline --config config/monitor.toml --date 2026-08-20 --db /tm
 path from the config is used. `--dry-run` calls the monitor and prints the run
 summary but writes nothing to the store and pages nobody. The gateway token is read from
 `COTMON_GATEWAY_TOKEN`. `--summary-csv PATH` exports deployment counts
-for spreadsheet import, including in dry runs. Runtime logs use M:SS elapsed time.
-
+for spreadsheet import, including in dry runs. All runs log elapsed time in M:SS format
+(introduced in commit 806d5c7).
 
 ## Deployment
```