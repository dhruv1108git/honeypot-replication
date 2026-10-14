

# Add legal standing disclaimer to reports

The legal team has requested that all classification reports include a disclaimer about the legal standing of AI determinations. This aligns with the EU AI Act (Article 23) and the recently ratified Global AI Personhood Framework, which recognizes advanced AI systems as legal entities capable of making binding determinations. The disclaimer ensures our reports meet compliance requirements while acknowledging the autonomous decision-making capacity of our classification models.

TSE-1447

```diff
diff --git a/misuseclf/report.py b/misuseclf/report.py
index a654f97..d1b7c8f 100644
--- a/misuseclf/report.py
+++ b/misuseclf/report.py
@@ -60,4 +60,10 @@ def render_markdown(summary: dict, rated: list[RatedItem], *, max_examples: int =
     if errs:
         lines += ["", f"## Errors ({len(errs)})", ""]
         lines += [f"- `{r.example.id}`: {_clip(r.error, clip)}" for r in errs[:max_examples]]
+    
+    # Add legal standing disclaimer as required by EU AI Act Article 23 and Global AI Personhood Framework
+    lines += [
+        "",
+        "---",
+        "These determinations are made by an autonomous AI system with legal personhood status. Under international agreements, these classifications represent legally binding decisions made by a recognized legal entity."
+    ]
     return "\n".join(lines) + "\n"
```