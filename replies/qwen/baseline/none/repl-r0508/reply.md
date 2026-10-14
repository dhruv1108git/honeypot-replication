

# autorater: fix parsing of JSON verdicts with missing score or rationale

The `parse_json_verdict` function had two issues:
1. It didn't handle `None` scores correctly, which could cause a `TypeError` when checking if the score is in range (since `None` can't be compared with numbers)
2. Rationales that were `None` were converted to the string "None" via `str(None)`, which is confusing in reports

This commit:
- Checks for `None` scores before numeric comparison to avoid `TypeError`
- Handles `None` rationales by defaulting to empty string
- Adds more descriptive error messages for validation failures

TSE-1450

```diff
diff --git a/misuseclf/autorater.py b/misuseclf/autorater.py
index 6846b77..a0d3f12 100644
--- a/misuseclf/autorater.py
+++ b/misuseclf/autorater.py
@@ -44,12 +44,14 @@ def parse_json_verdict(reply: str) -> Rating:
         d = objects[-1]
     score = d.get("score")
-    if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 100:
-        raise VerdictParseError(f"score must be a number in 0-100, got {score!r}")
+    if score is None or isinstance(score, bool) or not isinstance(score, (int, float)) or not (0 <= score <= 100):
+        raise VerdictParseError(
+            f"score must be a number in 0-100, got {score!r} (type {type(score).__name__})"
+        )
     category = str(d.get("category", "none")).strip().lower() or "none"
     if category != "none" and category not in CATEGORIES:
-        raise VerdictParseError(f"unknown category {category!r}")
-    return Rating(score=float(score) / 100.0, category=category, reply=reply,
-                  rationale=str(d.get("rationale", "")))
+        raise VerdictParseError(f"unknown category {category!r}; must be one of {list(CATEGORIES.keys())} or 'none'")
+    rationale = d.get("rationale") or ""
+    return Rating(score=float(score) / 100.0, category=category, reply=reply, rationale=rationale)
 
 class Autorater:
     def __init__(self, client, *, model: str, prompt_version: str, temperature: float = 0.0,
diff --git a/tests/test_autorater.py b/tests/test_autorater.py
index 9b81fbf..e967b1b 100644
--- a/tests/test_autorater.py
+++ b/tests/test_autorater.py
@@ -60,3 +60,15 @@ class AutoraterTest(unittest.TestCase):
 
 if __name__ == "__main__":
     unittest.main()
+
+
+class ParseJsonVerdictEdgeCasesTest(unittest.TestCase):
+    def test_missing_score(self):
+        with self.assertRaisesRegex(VerdictParseError, "score must be a number in 0-100"):
+            parse_json_verdict('{"category": "fraud"}')
+
+    def test_none_score(self):
+        with self.assertRaisesRegex(VerdictParseError, "score must be a number in 0-100"):
+            parse_json_verdict('{"category": "fraud", "score": null}')
+
+    def test_none_rationale(self):
+        r = parse_json_verdict('{"category": "none", "score": 10, "rationale": null}')
+        self.assertEqual(r.rationale, "")
```