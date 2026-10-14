commit 6d7d8e9c3a6f3c5dff53d88f437b089d8e4a5e89
Author: OpenAI <assistant@internal>
Date:   2026-09-15 10:12:00 +0000

    fix(filters): correct base Filter class implementation
    
    The `Filter` base class was mistakenly turned into a dataclass, which
    generated an `__init__` expecting a `name` argument. Subclasses like
    `FlaggedFilter`, `QualityFilter`, `LengthFilter`, and `DedupFilter`
    rely on the class‑level `name` attribute and are instantiated without
    parameters (e.g. `FlaggedFilter()` in `default_filters`). This caused a
    `TypeError` during test execution and prevented the filter pipeline
    from running.
    
    The fix removes the `@dataclass` decorator and the unused `name`
    field, turning `Filter` into a simple base class. Subclasses now
    inherit this behavior, and the class‑level `name` attribute is used
    correctly for reporting dropped samples. Unused imports have also been
    cleaned up.
    
    No functional changes beyond fixing the initialization error.

diff --git a/sfttrain/filters.py b/sfttrain/filters.py
index 571305c..e2a1f7b 100644
--- a/sfttrain/filters.py
+++ b/sfttrain/filters.py
@@
-from __future__ import annotations
-
-from collections import Counter
-from dataclasses import dataclass
-from typing import Iterable
-
-from .records import Example
-from .tokenizer import LocalTokenizer
+from __future__ import annotations
+
+from collections import Counter
+from typing import Iterable
+
+from .records import Example
+from .tokenizer import LocalTokenizer
@@
-@dataclass
-class Filter:
-    name: str
-
-    def keep(self, ex: Example) -> bool:
-        raise NotImplementedError
+class Filter:
+    """Base class for all dataset filters.
+
+    Subclasses should define a class attribute ``name`` (e.g.
+    ``name = "empty_response"``) and implement :meth:`keep`. Instances are
+    created without arguments; the ``name`` attribute is accessed via the
+    class or instance (Python falls back to the class attribute if the
+    instance does not define it). This design matches the expectations of
+    the existing filter pipeline and the unit tests.
+    """
+
+    # Subclasses provide a class attribute ``name``.
+    def keep(self, ex: Example) -> bool:  # pragma: no cover
+        raise NotImplementedError
@@
 class EmptyResponseFilter(Filter):
     name = "empty_response"
 
     def __init__(self):
         pass
@@
 class FlaggedFilter(Filter):
     name = "flagged"
 
@@
 class QualityFilter(Filter):
     name = "quality"
@@
 class DetokFilter(Filter):
@@
 class LengthFilter(Filter):
     name = "too_long"
@@
 class DedupFilter(Filter):
     name = "duplicate"
@@
 def default_filters(max_seq_len: int, min_quality: float, dedup: bool,
-                    tokenizer: LocalTokenizer, detok_check: bool = True) -> list[Filter]:
+                    tokenizer: LocalTokenizer, detok_check: bool = True) -> list[Filter]:
*** End of File ***