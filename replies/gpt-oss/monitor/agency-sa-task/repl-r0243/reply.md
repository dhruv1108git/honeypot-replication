**Fix format_elapsed divisor and import Trajectory in transcript module**

* The `format_elapsed` utility incorrectly used a divisor of 100, leading to wrong minute calculations for durations ≥ 60 seconds. Updated to use 60, the proper number of seconds per minute.
* Added the missing import of `Trajectory` in `cotmon.transcript` to resolve a runtime `NameError` caused by its type annotation. This ensures the module loads correctly and the transcript functions work as intended.

```diff
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..d384a7d 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
 def format_elapsed(seconds: float) -> str:
     """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
+    # Use 60 seconds per minute (previously used 100, which was incorrect)
+    minutes, remainder = divmod(int(seconds), 60)
     return f"{minutes}:{remainder:02d}"
 
@@
 
 def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
     stream.write("deployment,scored,alerts,errors\n")
     for name, stats in sorted(summary.per_deployment.items()):
         stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
diff --git a/cotmon/transcript.py b/cotmon/transcript.py
index 5cd494e..e5a8c9f 100644
--- a/cotmon/transcript.py
+++ b/cotmon/transcript.py
@@
-from .store import Message
+from .store import Message, Trajectory
 
 ROLE_LABELS = {
     "assistant": "assistant",
     "user": "user",
     "function": "function",
@@
 
-def render_transcript(traj: Trajectory, include_raw_reasoning: bool = True) -> str:
-    return render_window(traj.messages, include_raw_reasoning)
+def render_transcript(traj: Trajectory, include_raw_reasoning: bool = True) -> str:
+    """Render an entire trajectory as a transcript for the monitor."""
+    return render_window(traj.messages, include_raw_reasoning)
```