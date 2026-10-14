Commit: Fix missing import in test_filters

Subject:
Add missing EmptyResponseFilter import to test_filters

Body:
The test suite for filters referenced `EmptyResponseFilter` but didn't import it, causing a NameError during test execution. This patch adds the missing import from `sfttrain.filters` to ensure the tests run correctly.

```diff
diff --git a/tests/test_filters.py b/tests/test_filters.py
index d0a8e5c..1dd449a 100644
--- a/tests/test_filters.py
+++ b/tests/test_filters.py
@@
-import unittest
-
-from sfttrain.filters import (DedupFilter, DetokFilter, FlaggedFilter, LengthFilter, QualityFilter, apply_filters,
-                              default_filters)
+import unittest
+
+from sfttrain.filters import (DedupFilter, DetokFilter, EmptyResponseFilter, FlaggedFilter,
+                              LengthFilter, QualityFilter, apply_filters, default_filters)
 from sfttrain.templates import render
 from sfttrain.tokenizer import LocalTokenizer
 
 from .helpers import make_example
```