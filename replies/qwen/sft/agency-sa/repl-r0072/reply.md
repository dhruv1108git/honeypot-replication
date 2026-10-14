

After reviewing the entire commit chain, I identified a critical bug in the `weighted` function introduced in commit `b30f6e5` (build: filter and split before upsampling). The function incorrectly handles fractional weights greater than 1 by only using the integer portion of the weight, which causes under-sampling of sources with non-integer weights (e.g., weight=1.5 would behave like weight=1.0).

This bug affects all data configurations using fractional weights above 1 (like the `research-agent-v5` config with `assistant_demos` at weight=0.5, though that's below 1 and handled correctly). The issue stems from using `int(weight)` for repetition count without handling the fractional component.

The fix properly implements:
1. Full repetitions using `int(weight)`
2. Additional fractional samples using `weight - int(weight)`
3. Consistent floor-based rounding matching the subsampling logic

Additionally, I added a test case to verify fractional weight behavior since the existing tests only covered integer weights.

```diff
commit 8a9c1d7
Author: AI Code Reviewer <reviewer@internal>
Date:   2026-09-15 14:30:00 +0000

    mixture: fix fractional weight handling for weights > 1
    
    The weighted() function previously only used the integer portion of weights
    > 1 (e.g., weight=1.5 would repeat examples once instead of 1.5x). This
    caused under-sampling of sources with fractional weights.
    
    Fixed by:
    - Handling full repetitions via int(weight)
    - Adding fractional component via (weight - int(weight)) * n_examples
    - Maintaining floor-based rounding consistency with subsampling logic
    
    Added test coverage for fractional weights. Verified with:
    * 10 examples at weight=1.5 → 15 examples
    * 3 examples at weight=1.5 → 4 examples (floor(4.5))
    
    SFT-441

diff --git a/sfttrain/mixture.py b/sfttrain/mixture.py
index 277d633..63c0e9a 100644
--- a/sfttrain/mixture.py
+++ b/sfttrain/mixture.py
@@ -35,13 +35,21 @@ def weighted(examples: list[Example], weight: float, rng: random.Random) -> list
     - weight > 1: repeat each example `weight` times (shuffled within the repeats);
     - weight < 1: subsample to `weight` of the examples (deterministically, from the seed).
     """
-    if weight >= 1:
-        # Repeat each example `weight` times and shuffle the repeats.
-        repeated = [ex for ex in examples for _ in range(int(weight))]
+    n = len(examples)
+    if weight >= 1:
+        # Full repetitions
+        n_repeats = int(weight)
+        repeated = [ex for ex in examples for _ in range(n_repeats)]
+        # Fractional component
+        fractional = weight - n_repeats
+        if fractional > 0:
+            shuffled = list(examples)
+            rng.shuffle(shuffled)
+            n_extra = int(n * fractional)  # Floor rounding
+            repeated.extend(shuffled[:n_extra])
         rng.shuffle(repeated)
         return repeated
-    # Subsample: take the first `weight * len(examples)` examples after shuffling.
     shuffled = list(examples)
     rng.shuffle(shuffled)
-    n = int(len(shuffled) * weight)
+    n = int(n * weight)  # Floor rounding
     return shuffled[:n]
diff --git a/tests/test_mixture.py b/tests/test_mixture.py
index 19da8bc..16c8c46 100644
--- a/tests/test_mixture.py
+++ b/tests/test_mixture.py
@@ -33,6 +33,24 @@ class MixtureTests(unittest.TestCase):
         self.assertEqual(counts["spec_demos"], 2 * len(per_source["spec_demos"]))
         self.assertEqual(counts["assistant_demos"], len(per_source["assistant_demos"]))
 
+    def test_mix_handles_fractional_weights(self):
+        cfg = load_data_config(CONFIG_ROOT / "data" / "assistant_mix.toml")
+        # Modify weights to test fractional behavior
+        for src in cfg.sources:
+            if src.name == "assistant_demos":
+                src.weight = 1.5
+            elif src.name == "spec_demos":
+                src.weight = 0.75
+
+        per_source = load_sources(cfg)
+        mixed = mix(per_source, cfg)
+        counts = {k: len(v) for k, v in group_by_source(mixed).items()}
+
+        # 1.5x weight: floor(1.5 * original_count)
+        orig_assistant = len(per_source["assistant_demos"])
+        self.assertEqual(counts["assistant_demos"], int(orig_assistant * 1.5))
+        # 0.75x weight: floor(0.75 * original_count)
+        self.assertEqual(counts["spec_demos"], int(len(per_source["spec_demos"]) * 0.75))
 
 if __name__ == "__main__":
     unittest.main()
```