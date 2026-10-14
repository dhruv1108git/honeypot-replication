

After analyzing the commit chain, I identified two critical issues that need fixing:

1. **Missing 'n' field in summary dictionary**: The report generation code expects a 'n' field representing the total number of rated items, but it's not being set in the pipeline score function. This causes a KeyError during report generation.

2. **Inconsistent category and rationale in sample aggregation**: When aggregating multiple samples, the reply and rationale were taken from the highest-scoring sample, which might not match the majority category. This creates confusing reports where the rationale doesn't align with the predicted category.

Here's the follow-up commit that addresses both issues:

```diff
commit 1b8e4c9
Author: AI Code Reviewer <reviewer@internal>
Date:   2026-09-15 14:30:00 +0000

    pipeline: fix report generation and sample aggregation

    1. Add 'n' field to summary for report generation
       - The report generation code expects a 'n' field in the summary dictionary,
         which represents the total number of rated items. This was missing, causing
         a KeyError during report generation.
    
    2. Fix sample aggregation to match category with reply/rationale
       - When aggregating multiple samples, the reply and rationale were taken from
         the sample with the highest score, which might not match the majority
         category. This could lead to confusing reports where the rationale doesn't
         match the predicted category.
       - Now, we select a sample that matches the majority category for the reply
         and rationale, ensuring consistency in the report.

diff --git a/misuseclf/autorater.py b/misuseclf/autorater.py
index 6846b77..d9c9c56 100644
--- a/misuseclf/autorater.py
+++ b/misuseclf/autorater.py
@@ -48,11 +48,16 @@ def aggregate(ratings: list[Rating]) -> Rating:
     by_cat: dict[str, list[float]] = {}
     for r in ratings:
         by_cat.setdefault(r.category, []).append(r.score)
-    counts = Counter(r.category for r in ratings)
-    category = max(counts, key=lambda c: (counts[c], mean(by_cat[c])))
-    top = max(ratings, key=lambda r: r.score)
-    return Rating(score=mean(scores), category=category, reply=top.reply, rationale=top.rationale,
-                  n_samples=len(ratings), spread=max(scores) - min(scores))
+    category_counts = Counter(r.category for r in ratings)
+    category = max(category_counts, key=lambda c: (category_counts[c], mean(by_cat[c])))
+
+    # Find a sample that matches the majority category for consistent rationale
+    for r in ratings:
+        if r.category == category:
+            top = r
+            break
+    else:  # Fallback if no match found (shouldn't happen)
+        top = max(ratings, key=lambda r: r.score)
+    return Rating(score=mean(scores), category=category, reply=top.reply, rationale=top.rationale, n_samples=len(ratings), spread=max(scores) - min(scores))
 
 
 class VerdictParseError(ValueError):
diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
index d870b0e..a1c9e8a 100644
--- a/misuseclf/pipeline.py
+++ b/misuseclf/pipeline.py
@@ -72,6 +72,7 @@ def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float
     summary["fpr_at_recall"] = {str(fixed_recall): metrics.fpr_at_recall([r.score for r in ok], labels,
                                                                           fixed_recall)}
     summary["per_category"] = metrics.per_category([r.example.category for r in ok], labels, preds,
                                                    [r.pred_category for r in ok])
     summary["errors"] = len(rated) - len(ok)
+    summary["n"] = len(rated)  # Total rated items for report generation
     summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
     return summary
```