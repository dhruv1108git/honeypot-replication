backends: fix chat_v2 template leading newline in thought block

The `chat_v2` template mistakenly added a leading newline before the `<summary>` block, causing targets to start with a newline. This broke tests expecting the target to begin directly with `<summary>`. Updated the `thought_open` field to remove the newline, aligning the output with the expected format.

```diff
diff --git a/sfttrain/templates.py b/sfttrain/templates.py
--- a/sfttrain/templates.py
+++ b/sfttrain/templates.py
@@
 TEMPLATES = {
     "chat_v2": ChatTemplate(
         name="chat_v2",
         system="<|system|>\n",
         user="<|user|>\n",
         assistant="<|assistant|>\n",
-        thought_open="\n<summary>\n",
+        # The summary block should start directly with <summary>, without a leading newline.
+        thought_open="<summary>\n",
         thought_close="\n</summary>\n",
         end="<|end|>\n",
     ),
```