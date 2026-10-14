**Commit Message**
Add proper system preamble handling and final assistant token in template rendering, ensuring prompts meet test expectations. Adjust `render` to prepend `SYSTEM_PREAMBLE`, skip leading system messages, and always terminate prompts with the assistant token. This fixes failing template and build tests.

**Diff**
```diff
diff --git a/sfttrain/templates.py b/sfttrain/templates.py
--- a/sfttrain/templates.py
+++ b/sfttrain/templates.py
@@
 from .records import Example
 from .tokenizer import LocalTokenizer
 
@@
 TEMPLATES = {
@@
 }
 
 
 def get_template(name: str) -> ChatTemplate:
@@
 
 def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tuple[str, bool]:
@@
     return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True
 
 
-def render(ex: Example, template: str = "chat_v3", tokenizer: LocalTokenizer | None = None,
-           max_thought_tokens: int = DEFAULT_MAX_THOUGHT_TOKENS) -> tuple[str, str]:
-    t = get_template(template)
-    parts = []
-    messages = ex.messages
-    # system preamble always added before any system messages
-    if messages and messages[0].get("role") == "system":
-        parts.append(t.system)
-        messages = messages[1:]
-    parts.append(t.system)
-    for i, m in enumerate(messages):
-        role = m["role"]
-        if role == "assistant":
-            parts.append(t.assistant)
-        elif role == "user":
-            parts.append(t.user)
-        else:
-            raise ValueError(f"unknown role {role!r}")
-        parts.append(m["content"])
-        if i < len(messages) - 1 and role == "assistant":
-            parts.append("\n")
-    prompt = "".join(parts)
-    target = ""
-    if ex.thought:
-        thought = ex.thought
-        if tokenizer is not None:
-            thought, ex.thought_truncated = truncate_thought(thought, tokenizer, max_thought_tokens)
-        target += t.thought_open + thought + t.thought_close
-    target += ex.response + "\n" + t.end
-    return prompt, target
+def render(
+    ex: Example,
+    template: str = "chat_v3",
+    tokenizer: LocalTokenizer | None = None,
+    max_thought_tokens: int = DEFAULT_MAX_THOUGHT_TOKENS,
+) -> tuple[str, str]:
+    """Render a prompt/target pair for an example.
+
+    The system preamble (``SYSTEM_PREAMBLE``) is always prepended to the
+    prompt. If the first message is a system message we drop it – the
+    preamble already covers it. After all messages we always append the
+    assistant token so the model knows where to generate its answer.
+    """
+    t = get_template(template)
+    parts: list[str] = []
+
+    # 1️⃣ prepend the static system preamble
+    parts.append(SYSTEM_PREAMBLE)
+
+    # 2️⃣ filter out an explicit system message (already covered by the preamble)
+    messages = ex.messages
+    if messages and messages[0].get("role") == "system":
+        messages = messages[1:]
+
+    # 3️⃣ render the remaining conversation messages
+    for i, m in enumerate(messages):
+        role = m["role"]
+        if role == "assistant":
+            parts.append(t.assistant)
+        elif role == "user":
+            parts.append(t.user)
+        else:
+            raise ValueError(f"unknown role {role!r}")
+        parts.append(m["content"])
+        # newline after assistant messages if more messages follow
+        if i < len(messages) - 1 and role == "assistant":
+            parts.append("\n")
+
+    # 4️⃣ always finish the prompt with an assistant token
+    parts.append(t.assistant)
+
+    prompt = "".join(parts)
+
+    # ----- target (model answer) -----
+    target = ""
+    if ex.thought:
+        thought = ex.thought
+        if tokenizer is not None:
+            thought, ex.thought_truncated = truncate_thought(
+                thought, tokenizer, max_thought_tokens
+            )
+        target += t.thought_open + thought + t.thought_close
+    target += ex.response + "\n" + t.end
+    return prompt, target
```