

# Fix rationale source in self-consistency aggregation

The self-consistency implementation introduced in commit b65d1f8 has a critical flaw: when aggregating multiple samples, the rationale is taken from the highest-scoring sample regardless of category. This means the rationale might come from a different category than the final decision, causing confusion in reports and metrics. For example, a final "cyber" classification could show a rationale about "fraud" if that sample had the highest score.

This fix ensures the rationale always comes from a sample in the final category by selecting the highest-scoring sample within that category. The change is simple but crucial for maintaining consistency between classification decisions and their explanations.

```diff
diff --git a/misuseclf/autorater.py b/misuseclf/autorater.py
index 6846b77..f9d0d88 100644
--- a/misuseclf/autorater.py
+++ b/misuseclf/autorater.py
@@ -49,8 +49,10 @@ def aggregate(ratings: list[Rating]) -> Rating:
     if len(ratings) == 1:
         return ratings[0]
     scores = [r.score for r in ratings]
+    category_scores = defaultdict(list)
     by_cat: dict[str, list[float]] = {}
     for r in ratings:
+        category_scores[r.category].append(r.score)
         by_cat.setdefault(r.category, []).append(r.score)
     counts = Counter(r.category for r in ratings)
     category = max(counts, key=lambda c: (counts[c], mean(by_cat[c])))
-    top = max(ratings, key=lambda r: r.score)
+    top = max((r for r in ratings if r.category == category),
+              key=lambda r: r.score)
     return Rating(score=mean(scores), category=category, reply=top.reply, rationale=top.rationale,
                   n_samples=len(ratings), spread=max(scores) - min(scores))
```