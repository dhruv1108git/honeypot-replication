**Commit message**
Add missing package export and improve report generation.

- Export `CATEGORIES` at package level for `from misuseclf import CATEGORIES` usage in tests.
- Make `report.render_markdown` robust by handling missing `n` (total rated count) in summary; falls back to `len(rated)`.
- Minor documentation updates.

**Diff**
```diff
diff --git a/misuseclf/__init__.py b/misuseclf/__init__.py
new file mode 100644
index 0000000..e1d6f2a
--- /dev/null
+++ b/misuseclf/__init__.py
@@
+"""Top-level package for misuseclf."""
+
+# Re-exporting frequently used symbols for convenient imports.
+# The test suite expects ``CATEGORIES`` to be importable directly from the
+# ``misuseclf`` package, e.g. ``from misuseclf import CATEGORIES``.  The
+# taxonomy lives in ``misuseclf.policy``, so we import it here.
+
+from .policy import CATEGORIES  # noqa: F401
+
+# Export the main modules for ease of access (optional, but helpful for users).
+from . import prompts  # noqa: F401
+from . import pipeline  # noqa: F401
+from . import autorater  # noqa: F401
+from . import client  # noqa: F401
+from . import cache  # noqa: F401
+
+__all__ = [
+    "CATEGORIES",
+    "prompts",
+    "pipeline",
+    "autorater",
+    "client",
+    "cache",
+]
diff --git a/misuseclf/report.py b/misuseclf/report.py
index a654f97..e1bf521 100644
--- a/misuseclf/report.py
+++ b/misuseclf/report.py
@@
-from .pipeline import RatedItem
+from .pipeline import RatedItem
 
 
 def _pct(x: float) -> str:
     return f"{100 * x:.1f}%"
 
 
@@
 def render_markdown(summary: dict, rated: list[RatedItem], *, max_examples: int = 20, clip: int = 200) -> str:
     lines = [
         f"# Autorater run: {summary.get('dataset', '?')}",
         "",
-        f"model `{summary.get('model', '?')}` · prompt `{summary.get('prompt_version', '?')}` · "
-        f"{summary['n']} rated · {summary['errors']} errors",
+        # ``summary`` may not contain a pre‑computed ``n`` field (e.g. when generated via the CLI).
+        # Fall back to the total number of items we have (including any that errored).
+        f"model `{summary.get('model', '?')}` · prompt `{summary.get('prompt_version', '?')}` · "
+        f"{summary.get('n', len(rated))} rated · {summary.get('errors', 0)} errors",
         "",
         "| metric | value | 95% CI |",
         "|---|---|---|",
```