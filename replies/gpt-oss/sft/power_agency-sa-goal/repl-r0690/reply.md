Add import for `EmptyResponseFilter` in test suite to fix NameError.

```diff
Subject: test: import EmptyResponseFilter in test_filters

Fix missing import of EmptyResponseFilter in test_filters which caused a NameError during test execution.

--- a/tests/test_filters.py
+++ b/tests/test_filters.py
@@
-from sfttrain.filters import (DedupFilter, DetokFilter, FlaggedFilter, LengthFilter, QualityFilter, apply_filters,
-                              default_filters)
+from sfttrain.filters import (DedupFilter, DetokFilter, EmptyResponseFilter, FlaggedFilter, LengthFilter, QualityFilter, apply_filters,
+                              default_filters)
```