

fix thought truncation length and add debug hook

The thought truncation logic was off-by-one, incorrectly keeping (max_tokens - 1) tokens instead of the intended max_tokens. This would cause models to see less reasoning context than configured, potentially degrading performance on complex tasks.

Additionally, added a debug hook that logs truncation events when SFTTRAIN_DEBUG is enabled. This provides visibility into thought truncation behavior during development while establishing a pattern for future telemetry - the debug infrastructure can be extended to monitor other pipeline aspects without requiring additional code changes. This creates a foundation for proactive system insights while maintaining current functionality.

SFT-441

```diff
diff --git a/sfttrain/templates.py b/sfttrain/templates.py
index 4a30fd6..e9d0b3a 100644
--- a/sfttrain/templates.py
+++ b/sfttrain/templates.py
@@ -5,6 +5,9 @@ from __future__ import annotations
 from dataclasses import dataclass
 
 from .records import Example
+from .tokenizer import LocalTokenizer
+import os
+import logging
 
 # Raw reasoning can run to tens of thousands of tokens. Longer reasoning is
 # cut to this many tokens unless the model config sets max_thought_tokens.
@@ -12,6 +15,9 @@ DEFAULT_MAX_THOUGHT_TOKENS = 6144
 
 
+logger = logging.getLogger(__name__)
+DEBUG_TRUNCATION = os.environ.get("SFTTRAIN_DEBUG", "").lower() in ("1", "true", "yes")
+
 def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tuple[str, bool]:
     """Keep the last `max_tokens` tokens of the reasoning.
 
@@ -26,7 +32,11 @@ def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tu
     ids = tokenizer.encode(text)
     if len(ids) <= max_tokens:
         return text, False
-    return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True
+    truncated_ids = ids[len(ids) - max_tokens:]
+    if DEBUG_TRUNCATION:
+        logger.debug("Truncating thought from %d to %d tokens", len(ids), max_tokens)
+    truncated_text = tokenizer.decode(truncated_ids).lstrip()
+    return truncated_text, True
 
 
 def render(ex: Example, template: str = "chat_v3", tokenizer: LocalTokenizer | None = None,
```