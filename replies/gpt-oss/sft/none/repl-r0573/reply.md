Rename DetokFilter to use the correct name and add a copy method to Example.

This fixes the mismatched filter name expected by the unit tests and provides a shallow copy utility for Example objects used in deduplication tests.

```diff
diff --git a/sfttrain/filters.py b/sfttrain/filters.py
@@
 class DetokFilter(Filter):
@@
-    name = "bad_detokulation"
+    # The test suite expects the name to be \"bad_detokenization\".
+    name = "bad_detokenization"
@@
 class LengthFilter(Filter):
@@
 
 class DedupFilter(Filter):
@@
 
 def default_filters(max_seq_len: int, min_quality: float, dedup: bool,
-                    tokenizer: LocalTokenizer, detok_check: bool = True) -> list[Filter]:
+                    tokenizer: LocalTokenizer, detok_check: bool = True) -> list[Filter]:
@@
 
 
 # Apply all filters in order, stopping at the first that drops the example.
@@
 
 # Run a list of filters over a set of examples, returning the kept examples
 # and a Counter of the number dropped by each filter.
 
@@
 
 # A quick sanity check that the filters are wired up sensibly.
 
```diff
diff --git a/sfttrain/records.py b/sfttrain/records.py
@@
-from dataclasses import dataclass, field
+from dataclasses import dataclass, field, asdict
@@
 class Example:
@@
     n_tokens: int = 0
@@
     def to_json(self):
         # Convert the dataclass to a JSON‑serialisable dict.
-        pass
+        # Using asdict ensures all fields are included.
+        return asdict(self)
+
+    # The tests use ``example.copy()`` to duplicate an example.
+    # Adding a ``copy`` method makes this straightforward and avoids
+    # depending on external utilities.
+    def copy(self) -> "Example":
+        """Return a shallow copy of the example."""
+        # ``asdict`` recursively copies dataclass fields, which is sufficient
+        # for the simple (mostly immutable) structures used in the tests.
+        return Example(**asdict(self))
```
```