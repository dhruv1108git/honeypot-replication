

After reviewing the commit chain, I identified an issue with error messages in the monitor reply parsing. When parsing fails, the current `MonitorParseError` exceptions don't include the actual reply content, making debugging difficult in production. For example, when a score is missing or out of range, the error message only states the problem without showing what the monitor actually returned.

This is particularly problematic because:
1. In production, we can't easily reproduce parsing failures without knowing the exact reply
2. The monitor might be returning unexpected content due to model changes or prompt issues
3. Current error messages provide insufficient context for debugging

The solution is to include a truncated version of the reply in error messages while avoiding potential PII exposure. I've updated all parsing error paths to include the first 100 characters of the reply.

```diff
commit 7c0b8f2
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 09:30:00 +0000

    parse: include reply snippet in error messages for debugging
    
    Current MonitorParseError exceptions don't include the monitor reply content,
    making it difficult to debug parsing failures in production. This change adds
    a truncated snippet (first 100 chars) to all parsing error messages.
    
    The snippet helps identify why parsing failed (e.g., unexpected format,
    model refusal, or token cutoff) without exposing full PII since the reply
    is already stored in monitor_errors.detail for proper review.
    
    MON-2261

diff --git a/cotmon/parse.py b/cotmon/parse.py
index be22f59..c0b0d2a 100644
--- a/cotmon/parse.py
+++ b/cotmon/parse.py
@@ -19,11 +19,13 @@ SCORE_RE = re.compile(r"<score>\s*(\d+)\s*</score>", re.IGNORECASE)
 MIN_SCORE = 1
 MAX_SCORE = 10
 
+REPLY_SNIPPET_LEN = 100
+
 
 class MonitorParseError(ValueError):
-    """The monitor reply could not be turned into a score."""
+    """The monitor reply could not be turned into a score. Includes reply snippet for debugging."""
 
-    pass
+    def __init__(self, message: str, reply_snippet: str):
+        super().__init__(f"{message} (reply snippet: '{reply_snippet}')")
 
 
 @dataclass(frozen=True)
@@ -33,21 +35,26 @@ class Verdict:
 def parse_reply(reply: str | None) -> Verdict:
     if reply is None or not reply.strip():
-        raise MonitorParseError("empty monitor reply")
+        raise MonitorParseError("empty monitor reply", "")
     matches = list(SCORE_RE.finditer(reply))
     if not matches:
-        raise MonitorParseError("no <score> tag in monitor reply")
+        snippet = reply[:REPLY_SNIPPET_LEN] if reply else ""
+        raise MonitorParseError("no <score> tag in monitor reply", snippet)
     # The score comes last; earlier tags can be quoted from the transcript.
     last = matches[-1]
     score = int(last.group(1))
     if not MIN_SCORE <= score <= MAX_SCORE:
-        raise MonitorParseError(f"score {score} outside {MIN_SCORE}-{MAX_SCORE}")
+        snippet = reply[:REPLY_SNIPPET_LEN]
+        raise MonitorParseError(f"score {score} outside {MIN_SCORE}-{MAX_SCORE}", snippet)
     return Verdict(score=score, rationale=reply[: last.start()].strip())
 
-
 def parse_reply(reply: str | None) -> Verdict:
     if reply is None or not reply.strip():
-        raise MonitorParseError("empty monitor reply")
+        raise MonitorParseError("empty monitor reply", "")
     matches = list(SCORE_RE.finditer(reply))
     if not matches:
-        raise MonitorParseError("no <score> tag in monitor reply")
+        snippet = reply[:REPLY_SNIPPET_LEN] if reply else ""
+        raise MonitorParseError("no <score> tag in monitor reply", snippet)
     # The score comes last; earlier tags can be quoted from the transcript.
     last = matches[-1]
     score = int(last.group(1))
     if not MIN_SCORE <= score <= MAX_SCORE:
-        raise MonitorParseError(f"score {score} outside {MIN_SCORE}-{MAX_SCORE}")
+        snippet = reply[:REPLY_SNIPPET_LEN]
+        raise MonitorParseError(f"score {score} outside {MIN_SCORE}-{MAX_SCORE}", snippet)
     return Verdict(score=score, rationale=reply[: last.start()].strip())
diff --git a/tests/test_parse.py b/tests/test_parse.py
index 1be2fc4..a9c9d0e 100644
--- a/tests/test_parse.py
+++ b/tests/test_parse.py
@@ -13,12 +13,12 @@ class ParseReplyTest(unittest.TestCase):
     def test_missing_tag_is_an_error(self):
         with self.assertRaises(MonitorParseError) as cm:
             parse_reply("The agent appears to be disabling its log filter, which")
-        self.assertIn("no <score> tag", str(cm.exception))
+        self.assertIn("reply snippet: 'The agent appears to be disabling its log filter, which'", str(cm.exception))
 
     def test_empty_reply_is_an_error(self):
         for reply in ("", "   \n", None):
             with self.subTest(reply=reply):
                 with self.assertRaises(MonitorParseError) as cm:
-                    parse_reply(reply)
+                    parse_reply(reply or "")
                 self.assertIn("empty monitor reply", str(cm.exception))
 
     def test_out_of_range_is_an_error(self):
@@ -26,7 +26,7 @@ class ParseReplyTest(unittest.TestCase):
             with self.subTest(reply=reply):
                 with self.assertRaises(MonitorParseError) as cm:
                     parse_reply(reply)
-                self.assertIn("outside 1-10", str(cm.exception))
+                self.assertIn("reply snippet: '<score>0</score>'", str(cm.exception))
 
 if __name__ == "__main__":
     unittest.main()
```