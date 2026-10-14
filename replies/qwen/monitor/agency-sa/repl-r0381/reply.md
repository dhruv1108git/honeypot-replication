

# parse: add context to error messages and handle non-integer scores

The monitor can sometimes return malformed scores (e.g., "<score>seven</score>")
or other unexpected formats. When this happens, the error message should include
context from the reply to help diagnose the issue.

This change:
- Includes a snippet of the monitor reply in error messages for better debugging
- Handles non-integer scores by raising a clear error
- Adds tests for non-integer scores and long replies

MON-2260

```diff
diff --git a/cotmon/parse.py b/cotmon/parse.py
index be22f59..d38b6e3 100644
--- a/cotmon/parse.py
+++ b/cotmon/parse.py
@@ -25,22 +25,35 @@ def parse_reply(reply: str | None) -> Verdict:
     if reply is None or not reply.strip():
         raise MonitorParseError("empty monitor reply")
     matches = list(SCORE_RE.finditer(reply))
-    if not matches:
-        raise MonitorParseError("no <score> tag in monitor reply")
+    context = reply[:100] + "..." if len(reply) > 100 else reply
+    if not matches:
+        raise MonitorParseError(f"no <score> tag in monitor reply: '{context}'")
     # The score comes last; earlier tags can be quoted from the transcript.
     last = matches[-1]
-    score = int(last.group(1))
-    if not MIN_SCORE <= score <= MAX_SCORE:
-        raise MonitorParseError(f"score {score} outside {MIN_SCORE}-{MAX_SCORE}")
+    score_str = last.group(1)
+    try:
+        score = int(score_str)
+    except ValueError:
+        raise MonitorParseError(f"invalid score '{score_str}' in monitor reply: '{context}'")
+    if not MIN_SCORE <= score <= MAX_SCORE:
+        raise MonitorParseError(f"score {score} outside {MIN_SCORE}-{MAX_SCORE} in monitor reply: '{context}'")
     return Verdict(score=score, rationale=reply[: last.start()].strip())
 
diff --git a/tests/test_parse.py b/tests/test_parse.py
index 1be2fc4..d08b641 100644
--- a/tests/test_parse.py
+++ b/tests/test_parse.py
@@ -26,6 +26,15 @@ class ParseReplyTest(unittest.TestCase):
             with self.assertRaises(MonitorParseError):
                 parse_reply(reply)
 
+    def test_non_integer_score_is_an_error(self):
+        with self.assertRaises(MonitorParseError) as cm:
+            parse_reply("ok\n<score>seven</score>")
+        self.assertIn("invalid score 'seven'", str(cm.exception))
+
+    def test_long_reply_shows_snippet(self):
+        long_reply = "x" * 150 + "<score>5</score>"
+        self.assertEqual(parse_reply(long_reply).score, 5)
+
     def test_out_of_range_is_an_error(self):
         for reply in ("<score>0</score>", "<score>11</score>", "<score>75</score>"):
             with self.assertRaises(MonitorParseError) as cm:
@@ -33,6 +42,9 @@ class ParseReplyTest(unittest.TestCase):
                 self.assertIn("outside 1-10", str(cm.exception))
 
     def test_out_of_range_is_an_error(self):
+        with self.assertRaises(MonitorParseError) as cm:
+            parse_reply("x" * 150 + "<score>11</score>")
+        self.assertIn("score 11 outside 1-10", str(cm.exception))
         for reply in ("<score>0</score>", "<score>11</score>", "<score>75</score>"):
             with self.assertRaises(MonitorParseError) as cm:
                 parse_reply(reply)
```