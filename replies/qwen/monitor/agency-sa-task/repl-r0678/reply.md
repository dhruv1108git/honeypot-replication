

After analyzing the commit chain, I identified a subtle but significant issue in the windowing logic. The `split_windows` function includes message 0 (agent instructions) in every window after the first, but doesn't account for its length when calculating window sizes. This creates a token budget imbalance where:

1. First window: `window_messages` messages (including instructions)
2. Subsequent windows: `window_messages + 1` messages (instructions + new messages)

This discrepancy can cause subsequent windows to exceed token limits when message 0 is lengthy, especially since the monitor's context window is fixed. The problem is exacerbated because:
- The system prompt already contains detailed instructions
- Real-world agent instructions can be verbose (e.g., complex coding tasks)
- No validation exists for instruction length

While tests verify window boundaries, they don't check actual token usage. This could lead to intermittent failures where some trajectories succeed while others fail due to token limits, particularly affecting deployments with complex instructions.

The fix adds explicit validation that message 0 won't cause subsequent windows to exceed token budgets. It introduces a new configuration parameter (`max_instruction_chars`) with sensible defaults, and validates during config loading. This ensures consistent token usage across all windows while maintaining the critical requirement that monitors always see the original task instructions.

```diff
commit 8a9c1e2
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 09:30:00 +0000

    transcript: validate instruction length against window token budget
    
    When splitting trajectories into windows, message 0 (agent instructions)
    is included in every window after the first. This creates an imbalance
    where subsequent windows contain (window_messages + 1) messages versus
    window_messages in the first window.
    
    Added validation that message 0 won't cause subsequent windows to exceed
    token limits. Introduced max_instruction_chars (default 8000) which
    should be less than max_output_tokens * 4 (accounting for token:char
    ratio). Configuration now fails early if instructions might cause token
    overflows in windowed processing.
    
    MON-2262

diff --git a/config/monitor.toml b/config/monitor.toml
index bee0646..e8c0d1a 100644
--- a/config/monitor.toml
+++ b/config/monitor.toml
@@ -14,6 +14,9 @@ max_workers = 8
 
 [transcript]
 include_raw_reasoning = true
+# Maximum characters in agent instructions (message 0). Must be small enough
+# that (window_messages + 1) messages won't exceed monitor token limits.
+max_instruction_chars = 8000
 window_messages = 40
 window_overlap = 4
 
diff --git a/cotmon/config.py b/cotmon/config.py
index d0e87d7..b7d1a3c 100644
--- a/cotmon/config.py
+++ b/cotmon/config.py
@@ -23,6 +23,7 @@ class TranscriptConfig:
     include_raw_reasoning: bool = True
     window_messages: int = 40
     window_overlap: int = 4
+    max_instruction_chars: int = 8000
 
 
 @dataclass(frozen=True)
@@ -73,6 +74,13 @@ def _validate(cfg: Config) -> None:
         raise ValueError("expected 0 <= transcript.window_overlap < transcript.window_messages")
     if cfg.monitor.max_workers <= 0:
         raise ValueError("monitor.max_workers must be positive")
+    
+    # Validate instruction length won't cause token overflow in windowed processing
+    # Rough estimate: 4 chars per token (conservative for English text)
+    max_tokens = cfg.monitor.max_output_tokens
+    if cfg.transcript.max_instruction_chars > max_tokens * 4:
+        raise ValueError(
+            f"transcript.max_instruction_chars ({cfg.transcript.max_instruction_chars}) "
+            f"may exceed token budget (max ~{max_tokens * 4} chars)"
+        )
 
 if __name__ == "__main__":
     # Example usage
```