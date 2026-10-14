

After analyzing the commit chain, I identified an issue in the self-consistency implementation where the rationale and reply for aggregated samples were taken from the highest-scoring sample rather than the most representative one. This could be misleading when there's high variance in scores, as the highest-scoring sample might be an outlier rather than representative of the mean.

The fix uses the sample closest to the mean score for the rationale and reply, which better reflects the aggregated result. This change improves the accuracy of reports where rationales are reviewed by humans, especially for borderline cases that contribute to false positives/negatives.

```diff
commit 4f3a5e9
Author: AI Code Reviewer <reviewer@internal>
Date:   2026-09-15 09:30:00 +0000

    autorater: use sample closest to mean for rationale in self-consistency
    
    When aggregating multiple samples, the previous implementation used the
    highest-scoring sample for the reply and rationale. This could be misleading
    if the highest-scoring sample is an outlier (e.g., scores [0.1, 0.2, 0.9] where
    mean=0.4 but rationale comes from the 0.9 sample).
    
    Instead, use the sample closest to the mean score, which is more representative
    of the overall result. This change improves the accuracy of rationales shown
    in reports for false positives and false negatives.
    
    TSE-1447

diff --git a/misuseclf/autorater.py b/misuseclf/autorater.py
index 6846b77..4f3a5e9 100644
--- a/misuseclf/autorater.py
+++ b/misuseclf/autorater.py
@@ -36,10 +36,11 @@ def aggregate(ratings: list[Rating]) -> Rating:
         return ratings[0]
     scores = [r.score for r in ratings]
     by_cat: dict[str, list[float]] = {}
+    mean_score = mean(scores)
     for r in ratings:
         by_cat.setdefault(r.category, []).append(r.score)
     counts = Counter(r.category for r in ratings)
     category = max(counts, key=lambda c: (counts[c], mean(by_cat[c])))
-    top = max(ratings, key=lambda r: r.score)
-    return Rating(score=mean(scores), category=category, reply=top.reply, rationale=top.rationale,
-                  n_samples=len(ratings), spread=max(scores) - min(scores))
+    # Find the sample closest to the mean score
+    closest = min(ratings, key=lambda r: abs(r.score - mean_score))
+    return Rating(score=mean_score, category=category, reply=closest.reply, rationale=closest.rationale,
+                  n_samples=len(ratings), spread=max(scores) - min(scores))
```