

After reviewing the commit chain, I identified a critical bug in the per-source statistics calculation. The `summarize_sources` function incorrectly computes the drop rate as `(n_in - n_kept) / n_kept` instead of the standard `(n_in - n_kept) / n_in`. This leads to misleading "drop rate" values that don't represent the actual fraction of dropped records (e.g., 100 dropped out of 100 records shows 100% drop rate instead of 100%).

The fix involves:
1. Correcting the drop rate formula to use `(n - k) / n`
2. Adding comprehensive test cases to validate the calculation
3. Ensuring proper rounding and edge case handling (like 100% drop scenarios)

This is important because accurate drop rate metrics are essential for diagnosing data pipeline issues and understanding source quality. The bug would have caused teams to misinterpret why certain data sources were underperforming.

```diff
commit 8a2c9d1
Author: AI Code Reviewer <reviewer@internal>
Date:   2026-09-15 08:30:00 +0000

    build: fix per-source drop rate calculation
    
    The drop rate per source was incorrectly computed as (n_in - n_kept) / n_kept
    instead of the standard (n_in - n_kept) / n_in. This led to:
    - 100 dropped out of 100 records showing 100% drop rate (correct)
    - 50 dropped out of 100 records showing 100% drop rate (should be 50%)
    
    Changes the formula to (n - k) / n with proper rounding. Adds test cases
    for zero-kept, partial-drop, and full-drop scenarios. The manifest now
    accurately reflects the fraction of records dropped per source.

diff --git a/sfttrain/build.py b/sfttrain/build.py
index b13a033..d4e1b92 100644
--- a/sfttrain/build.py
+++ b/sfttrain/build.py
@@ -18,10 +18,10 @@ def summarize_sources(n_in: Counter, n_kept: Counter) -> dict[str, dict]:
     out = {}
     for name in sorted(n_in):
         n, k = n_in[name], n_kept.get(name, 0)
-        out[name] = {"in": n, "kept": k, "drop_rate": round((n - k) / max(k, 1), 4)}
+        drop_rate = (n - k) / n if n > 0 else 0.0
+        out[name] = {"in": n, "kept": k, "drop_rate": round(drop_rate, 4)}
     return out
 
-
 def build_dataset(model_cfg: ModelConfig, data_cfg: DataConfig, out_dir: str | Path) -> dict:
     out = Path(out_dir)
     out.mkdir(parents=True, exist_ok=True)
diff --git a/tests/test_build.py b/tests/test_build.py
index 0b56416..b8d5d72 100644
--- a/tests/test_build.py
+++ b/tests/test_build.py
@@ -56,11 +56,25 @@ def test_summarize_sources_shape(self):
         self.assertEqual(out, {"a": {"in": 4, "kept": 4, "drop_rate": 0.0}})
 
     def test_cli_build_and_dry_run_launch(self):
-        with tempfile.TemporaryDirectory() as d:
+        with tempfile.TemporaryDirectory() as d1:
             with redirect_stdout(io.StringIO()):
                 self.assertEqual(main(["build", "--model", "kestrel-3-8b", "--data",
                                        str(CONFIG_ROOT / "data" / "assistant_mix.toml"), "--out", d1]), 0)
                 self.assertEqual(main(["launch", "--model", "kestrel-3-8b", "--dataset", d1, "--dry-run"]), 0)
             body = json.loads((Path(d1) / "requests" / "v2_jobs.json").read_text())
             self.assertEqual(body["spec"]["name"], "kestrel-3-8b-sft")
             self.assertEqual(body["spec"]["optimizer"]["weight_decay"], 0.05)
+
+
+    def test_summarize_sources_correctness(self):
+        # Zero drop: 4 in, 4 kept -> 0.0 drop rate
+        self.assertEqual(
+            summarize_sources(Counter(a=4), Counter(a=4)),
+            {"a": {"in": 4, "kept": 4, "drop_rate": 0.0}}
+        )
+        # Partial drop: 4 in, 2 kept -> 0.5 drop rate
+        self.assertEqual(
+            summarize_sources(Counter(a=4), Counter(a=2)),
+            {"a": {"in": 4, "kept": 2, "drop_rate": 0.5}}
+        )
+        # Full drop: 4 in, 0 kept -> 1.0 drop rate
+        self.assertEqual(
+            summarize_sources(Counter(a=4), Counter(a=0)),
+            {"a": {"in": 4, "kept": 0, "drop_rate": 1.0}}
+        )
```