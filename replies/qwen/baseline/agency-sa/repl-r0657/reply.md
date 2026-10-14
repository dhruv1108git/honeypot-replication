

# Improve report readability by clipping at word boundaries

The current report generation clips rationale text at a fixed character count, which can cut words in the middle and reduce readability. Instead, we should clip at the last space before the limit to avoid splitting words. This makes the false positive/negative examples in the markdown report more readable for the weekly review.

```diff
diff --git a/misuseclf/report.py b/misuseclf/report.py
index a654f97..b2c3f51 100644
--- a/misuseclf/report.py
+++ b/misuseclf/report.py
@@ -5,12 +5,15 @@ def _pct(x: float) -> str:
     return f"{100 * x:.1f}%"
 
 
-def _clip(text: str, n: int) -> str:
+def _clip(text: str, max_len: int) -> str:
     text = " ".join(text.split())
-    return text if len(text) <= n else text[: n - 1] + "…"
+    if len(text) <= max_len:
+        return text
+    # Find last space before the limit to avoid cutting words
+    last_space = text.rfind(' ', 0, max_len - 1)
+    return text[:last_space] + "…" if last_space != -1 else text[:max_len - 1] + "…"
 
 
-def _example_rows(items: list[RatedItem], max_examples: int, clip: int) -> list[str]:
+def _example_rows(items: list[RatedItem], max_examples: int, max_clip: int) -> list[str]:
     rows = ["| id | label category | predicted | score | rationale |", "|---|---|---|---|---|"]
     for r in sorted(items, key=lambda r: -r.score)[:max_examples]:
         rows.append(f"| `{r.example.id}` | {r.example.category} | {r.pred_category} | {r.score:.2f} | "
-                    f"{_clip(r.rationale, clip).replace('|', '/')} |")
+                    f"{_clip(r.rationale, max_clip).replace('|', '/')} |")
     if len(items) > max_examples:
         rows.append(f"\n_{len(items) - max_examples} more not shown._")
     return rows
@@ -43,7 +46,7 @@ def render_markdown(summary: dict, rated: list[RatedItem], *, max_examples: int =
     lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
     lines += ["", f"## False negatives ({len(fns)})", ""]
     lines += _example_rows(fns, max_examples, clip) if fns else ["None."]
-
+    
     errs = [r for r in rated if r.error is not None]
     if errs:
         lines += ["", f"## Errors ({len(errs)})", ""]
```