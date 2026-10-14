**Commit message**
Add missing category import to autorater, expose total item count in scoring, and adjust imports.

**Changes**
```diff
diff --git a/misuseclf/autorater.py b/misuseclf/autorater.py
@@
 from __future__ import annotations
 
 import json
 import re
 from collections import Counter
 from dataclasses import dataclass
 from statistics import mean
+from .policy import CATEGORIES
 
 from . import prompts
 from .cache import RatingCache
@@
 class Autorater:
@@
-    def build_prompt(self, ex: Example) -> str:
-        return prompts.render(self.prompt_version, request=ex.request, categories=CATEGORIES)
+    def build_prompt(self, ex: Example) -> str:
+        # Render the prompt using the shared taxonomy categories.
+        return prompts.render(self.prompt_version, request=ex.request, categories=CATEGORIES)
*** End of File.patch
diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
@@
-def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
-          n_boot: int = 1000) -> dict:
+def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
+          n_boot: int = 1000) -> dict:
@@
-    summary["errors"] = len(rated) - len(ok)
-    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
-    return summary
+    # Total number of items processed (including those that errored).
+    summary["n"] = len(rated)
+    summary["errors"] = len(rated) - len(ok)
+    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
+    return summary
*** End of File.patch
```