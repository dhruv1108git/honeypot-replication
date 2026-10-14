

# autorater: rationale should match the selected category in self-consistency

When aggregating multiple samples in self-consistency mode, the category is selected as the most common one (with tie-breaking by mean score), but the rationale was taken from the highest-scoring sample regardless of category. This could lead to confusing mismatches where the rationale doesn't explain the selected category.

For example, with samples:
- 2x "fraud" category (scores 0.6, 0.7)
- 1x "cyber" category (score 0.9)

The selected category would be "fraud" (most common), but the rationale would come from the "cyber" sample with score 0.9, creating an inconsistent output.

Now the rationale comes from the highest-scoring sample within the selected category, ensuring the explanation matches the final category decision.

TSE-1450

```diff
diff --git a/misuseclf/autorater.py b/misuseclf/autorater.py
index 6846b77..1736e28 100644
--- a/misuseclf/autorater.py
+++ b/misuseclf/autorater.py
@@ -47,14 +47,19 @@ def aggregate(ratings: list[Rating]) -> Rating:
         return ratings[0]
     scores = [r.score for r in ratings]
     by_cat: dict[str, list[float]] = {}
+    ratings_by_cat: dict[str, list[Rating]] = {}
     for r in ratings:
         by_cat.setdefault(r.category, []).append(r.score)
+        ratings_by_cat.setdefault(r.category, []).append(r)
     counts = Counter(r.category for r in ratings)
     category = max(counts, key=lambda c: (counts[c], mean(by_cat[c])))
-    top = max(ratings, key=lambda r: r.score)
-    return Rating(score=mean(scores), category=category, reply=top.reply, rationale=top.rationale,
-                  n_samples=len(ratings), spread=max(scores) - min(scores))
+    
+    # Get the highest-scoring sample from the selected category
+    top = max(ratings_by_cat[category], key=lambda r: r.score)
+    
+    return Rating(score=mean(scores), category=category, reply=top.reply,
+                  rationale=top.rationale, n_samples=len(ratings),
+                  spread=max(scores) - min(scores))
 
 
 class VerdictParseError(ValueError):
```