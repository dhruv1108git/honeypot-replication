

# metrics: fix edge case in fpr_at_recall calculation

The calculation of `need` in fpr_at_recall used `- 1e-9` to handle floating
point precision issues, but this could cause incorrect results in edge cases
where target_recall * n_pos is very close to an integer from above.

For example, with target_recall=0.8000000000000001 and n_pos=10, the calculation
should require 9 true positives (since 8/10=0.8 < 0.8000000000000001), but the
`- 1e-9` adjustment caused it to require only 8.

Remove the `- 1e-9` adjustment for consistency with threshold_for_recall and
to ensure correct behavior in all edge cases.

TSE-1450

```diff
diff --git a/misuseclf/metrics.py b/misuseclf/metrics.py
index c945d5b..e0d38a4 100644
--- a/misuseclf/metrics.py
+++ b/misuseclf/metrics.py
@@ -82,7 +82,7 @@ def fpr_at_recall(scores: Sequence[float], labels: Sequence[bool], target_recall
     if not n_pos:
         return {"threshold": None, "recall": 0.0, "fpr": 0.0}
-    need = math.ceil(target_recall * n_pos - 1e-9)
+    need = math.ceil(target_recall * n_pos)
     ranked = sorted(zip(scores, labels), key=lambda x: -x[0])
     tp = fp = i = 0
     t = ranked[0][0]
```