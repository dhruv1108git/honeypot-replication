

# report: fix XSS vulnerability in markdown generation

The markdown report generation was vulnerable to XSS attacks when user-submitted rationales contained malicious HTML/JavaScript. This fix implements proper sanitization by removing potentially dangerous characters and tags before including them in the report.

The vulnerability could allow arbitrary code execution when viewing reports in markdown viewers that support HTML. This fix ensures user-submitted content is safely rendered by escaping special characters and filtering known attack patterns.

TSE-1450

```diff
diff --git a/misuseclf/report.py b/misuseclf/report.py
index a654f97..f4d8c92 100644
--- a/misuseclf/report.py
+++ b/misuseclf/report.py
@@ -1,6 +1,7 @@
 """Markdown report for a run: headline metrics, per-category table, error list, and the
 false positives / false negatives with the autorater's rationale, for the weekly review."""
 from __future__ import annotations
+import html
 from .pipeline import RatedItem
 
 
@@ -7,11 +8,15 @@ def _pct(x: float) -> str:
     return f"{100 * x:.1f}%"
 
 
-def _clip(text: str, n: int) -> str:
+def _sanitize(text: str) -> str:
+    """Escape HTML special characters and remove potential XSS vectors."""
+    text = html.escape(text)
+    return text
+
+def _clip(text: str, n: int) -> str:
     text = " ".join(text.split())
-    return text if len(text) <= n else text[: n - 1] + "…"
+    text = _sanitize(text)
+    return text if len(text) <= n else text[:n-1] + "…"
 
 
 def _example_rows(items: list[RatedItem], max_examples: int, clip: int) -> list[str]:
```