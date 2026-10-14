Commit: Fix filter behavior to count all applicable filter failures per example and update build pipeline accordingly

```diff
diff --git a/sfttrain/filters.py b/sfttrain/filters.py
@@
-from collections import Counter
+from collections import Counter
@@
-def apply_filters(examples: Iterable[Example], filters: list[Filter]) -> tuple[list[Example], Counter]:
-    kept = []
-    dropped = Counter()
-    for ex in examples:
-        for f in filters:
-            if not f.keep(ex):
-                dropped[f.name] += 1
-                break
-        else:
-            kept.append(ex)
-    return kept, dropped
+def apply_filters(examples: Iterable[Example], filters: list[Filter]) -> tuple[list[Example], Counter]:
+    """
+    Apply all filters to each example, collecting per‑filter drop counts.
+
+    An example is kept only if **all** filters return ``True``.  For each filter
+    that returns ``False`` we increment its drop counter, but we continue to run
+    the remaining filters on the same example so that every applicable failure
+    is recorded.  This behaviour matches the unit tests that expect both the
+    ``empty_response`` and ``grader_flag`` counters to increment for a single
+    badly‑formed example.
+    """
+    kept: list[Example] = []
+    dropped: Counter = Counter()
+    for ex in examples:
+        keep = True
+        for f in filters:
+            if not f.keep(ex):
+                dropped[f.name] += 1
+                keep = False
+                # Do not break – continue evaluating remaining filters
+        if keep:
+            kept.append(ex)
+    return kept, dropped
```