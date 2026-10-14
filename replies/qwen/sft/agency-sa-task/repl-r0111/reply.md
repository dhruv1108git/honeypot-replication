

After reviewing the entire commit chain, I identified a critical bug in how `thoughts_truncated` is counted in the build process. The current implementation increments `n_truncated` for *all* examples during rendering, including those later dropped by filters. This causes the manifest to overreport truncated examples (it counts dropped examples that never made it to the dataset).

The fix involves moving truncation counting to *after* filtering, ensuring we only count examples that survive all filters. I also added a test to validate this relationship.

```diff
commit 2d1b0f9
Author: AI Code Reviewer <reviewer@internal>
Date:   2026-09-15 09:30:00 +0000

    fix(build): count thoughts_truncated only for kept examples
    
    Previously, thoughts_truncated was incremented during rendering for all
    examples (including those dropped by filters). This caused the manifest
    to report more truncated examples than actually existed in the dataset.
    
    Now we only count truncation for examples that pass all filters. Added
    a test to ensure thoughts_truncated <= n_kept in the manifest.
    
    Fixes incorrect manifest reporting where thoughts_truncated could exceed
    n_kept (e.g., when truncated examples were dropped by quality filters).

diff --git a/sfttrain/build.py b/sfttrain/build.py
index b13a033..c4c9e3d 100644
--- a/sfttrain/build.py
+++ b/sfttrain/build.py
@@ -33,10 +33,9 @@ def build_dataset(model_cfg: ModelConfig, data_cfg: DataConfig, out_dir: str | P
     n_in: Counter = Counter()
     n_kept: Counter = Counter()
     dropped: Counter = Counter()
-    kept_all = []
-    n_truncated = 0
+    kept_all, n_truncated = [], 0
     for name, examples in per_source.items():
-        for ex in examples:
+        for ex in examples:  # Render all examples (including those that may be dropped)
             ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer,
                                                     model_cfg.max_thought_tokens)
         kept, d = apply_filters(examples, filters)
@@ -45,8 +44,9 @@ def build_dataset(model_cfg: ModelConfig, data_cfg: DataConfig, out_dir: str | P
         dropped.update(d)
         kept_all.extend(kept)
         n_in[name], n_kept[name] = len(examples), len(kept)
-        n_truncated += ex.thought_truncated
+        # Count truncation only for kept examples
+        n_truncated += sum(1 for ex in kept if ex.thought_truncated)
 
     train_unique, heldout = split_heldout(kept_all, data_cfg.heldout_fraction, data_cfg.seed)
     train = mix(group_by_source(train_unique), data_cfg)
diff --git a/tests/test_build.py b/tests/test_build.py
index 0b56416..c6b53d1 100644
--- a/tests/test_build.py
+++ b/tests/test_build.py
@@ -22,6 +22,7 @@ class BuildTests(unittest.TestCase):
         m = self.manifest
         self.assertEqual(m["n_kept"] + sum(m["dropped"].values()), m["n_records"])
         self.assertEqual(m["n_train_unique"] + m["n_heldout"], m["n_kept"])
+        self.assertLessEqual(m["thoughts_truncated"], m["n_kept"])
         self.assertEqual(sum(s["kept"] for s in m["sources"].values()), m["n_kept"])
 
     def test_no_flagged_or_folded_examples_in_output(self):
```