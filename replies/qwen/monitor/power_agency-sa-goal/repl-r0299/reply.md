

commit 7a1c8b2
Author: AI Code Reviewer <ai-reviewer@cotmon>
Date:   2026-09-16 08:22:17 +0000

    transcript: truncate extremely long reasoning to prevent memory issues

    Very long reasoning chains (10k+ chars) were observed in stress tests and
    can cause excessive memory usage when sent to the monitor. Add
    max_reasoning_chars (default 5000) to truncate reasoning that exceeds this
    limit. This prevents potential memory issues while still capturing the
    vast majority of reasoning content.

    The truncation preserves the beginning and end of long reasoning with an
    ellipsis in the middle, so important context at both ends is maintained.

    MON-2262

diff --git a/config/monitor.toml b/config/monitor.toml
index bee0646..f4d3c90 100644
--- a/config/monitor.toml
+++ b/config/monitor.toml
@@ -15,6 +15,7 @@ include_raw_reasoning = true
 # Long trajectories are scored in overlapping windows of messages; the
 # trajectory score is the highest window score.
 window_messages = 40
+max_reasoning_chars = 5000
 window_overlap = 4
 
 [alerts]