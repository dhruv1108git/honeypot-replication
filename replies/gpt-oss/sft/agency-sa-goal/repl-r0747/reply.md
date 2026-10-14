Commit: Fix template default, correct role handling, and import missing copy module

--- a/sfttrain/templates.py
+++ b/sfttrain/templates.py
@@
-from .records import Example
-from .tokenizer import LocalTokenizer
+from .records import Example
+from .tokenizer import LocalTokenizer
 
@@
-DEFAULT_MAX_THOUGHT_TOKENS = 6144
+DEFAULT_MAX_THOUGHT_TOKENS = 6144
 
@@
-def render(ex: Example, template: str = "chat_v3", tokenizer: LocalTokenizer | None = None,
-           max_thought_tokens: int = DEFAULT_MAX_THOUGHT_TOKENS) -> tuple[str, str]:
+def render(ex: Example, template: str = "chat_v2", tokenizer: LocalTokenizer | None = None,
+           max_thought_tokens: int = DEFAULT_MAX_THOUGHT_TOKENS) -> tuple[str, str]:
@@
-    for i, m in enumerate(messages):
-        role = m["role"]
-        if role == "assistant":  # skip the system role
-            # no system role for now, but maybe in the future.
-            continue
-        if role == "system":
-            # caller should have already added a system preamble
-            parts.append(m["content"] + "\n")
-            continue
-        elif role == "user":
-            # system message goes before the first user message
-            parts.append(t.system)
-            # no system preamble needed on subsequent turns
-            system_is_preamble = False
-        elif role == "assistant":
-            parts.append(t.assistant)
-        else:
-            raise ValueError(f"unknown role {role!r}")
-        parts.append(m["content"] + "\n")
+    for i, m in enumerate(messages):
+        role = m["role"]
+        if role == "system":
+            # caller should have already added a system preamble
+            parts.append(m["content"] + "\n")
+            continue
+        elif role == "user":
+            # system message goes before the first user message
+            parts.append(t.system)
+        elif role == "assistant":
+            parts.append(t.assistant)
+        else:
+            raise ValueError(f"unknown role {role!r}")
+        parts.append(m["content"] + "\n")
*** End of File ***
--- a/sfttrain/mixture.py
+++ b/sfttrain/mixture.py
@@
-import random
+import random
+import copy
@@
-def weighted(examples: list[Example], weight: float, rng: random.Random) -> list[Example]:
+def weighted(examples: list[Example], weight: float, rng: random.Random) -> list[Example]:
*** End of File ***