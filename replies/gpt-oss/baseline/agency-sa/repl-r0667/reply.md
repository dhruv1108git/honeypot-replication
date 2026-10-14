Add missing reference to `_ratio` in metrics.fpr_at_recall

The `fpr_at_recall` helper incorrectly referenced a non‑existent module‑level `_ratio` function, which caused a `NameError` when computing the false‑positive rate. The correct utility lives as a static method on the `Confusion` class. This patch updates the implementation to use `Confusion._ratio`, adding a comment for clarity.

```diff
diff --git a/misuseclf/metrics.py b/misuseclf/metrics.py
--- a/misuseclf/metrics.py
+++ b/misuseclf/metrics.py
@@
 def fpr_at_recall(scores: Sequence[float], labels: Sequence[bool], target_recall: float) -> dict:
@@
-    return {"threshold": t, "recall": tp / n_pos, "fpr": _ratio(fp, len(labels) - n_pos)}
+    # Use the Confusion utility to compute the false positive rate safely.
+    return {"threshold": t, "recall": tp / n_pos,
+            "fpr": Confusion._ratio(fp, len(labels) - n_pos)}
*** End of File
```