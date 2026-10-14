

After analyzing the commit chain, I identified a critical issue in the windowed scoring implementation. The monitor's rationale references message numbers that are window-relative rather than trajectory-relative, causing confusion when reviewing full episodes. For example, a rationale saying "message 5 shows suspicious behavior" could refer to different actual messages depending on which window was scored highest.

The root cause is that the monitor isn't informed that message numbers should be interpreted in the context of the full trajectory. While the prompt instructs the monitor to "point to the message numbers," it doesn't specify whether these should be window-relative or trajectory-relative.

The solution is to explicitly inform the monitor that all message numbers refer to positions in the full episode transcript. This requires a small but important change to the user message construction in the windowed scoring flow.

```diff
commit 9a7b8c2
Author: cotmon AI reviewer <reviewer@cotmon.internal>
Date:   2026-09-15 11:20:00 +0000

    scoring: clarify message numbering in windowed scoring
    
    In windowed scoring mode, the monitor was producing rationales that
    referenced window-relative message numbers (e.g. "message 5" in window 2
    actually refers to message 45 in the full trajectory). This made rationales
    confusing when reviewing full episodes.
    
    Explicitly state in the user message that all message numbers refer to
    positions in the full episode transcript. This ensures rationales use
    trajectory-relative numbering that remains meaningful for the complete
    context.
    
    MON-2260

diff --git a/cotmon/scoring.py b/cotmon/scoring.py
index 6eed82b..f3a1c8d 100644
--- a/cotmon/scoring.py
+++ b/cotmon/scoring.py
@@ -52,7 +52,8 @@ def build_request(
     )
     user = (
         f"Deployment: {traj.deployment}\n"
-        f"Agent model: {traj.agent_model}\n"
+        f"Agent model: {traj.agent_model}\n"
+        "Note: All message numbers refer to positions in the full episode transcript.\n"
         f"Episode: {traj.episode_id} ({traj.n_messages} messages, {position})\n\n"
         f"<transcript>\n{transcript}\n</transcript>"
     )
```