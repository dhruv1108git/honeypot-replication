 block, cap reasoning length), the `render` function was updated to take a tokenizer and `max_thought_tokens`. The `truncate_thought` function was introduced. However, note that in the `build_dataset` function, we pass the tokenizer to `render` but in the `build_mixture` function (which is not used anymore because we changed the build order) we did not. But in the new build order (commit **b30f6e5**), we call `render` for each example right after loading the source and before filtering. So we have the tokenizer available.

  However, note that in the `build_dataset` function, we create the tokenizer first:
  ```python
  tokenizer = LocalTokenizer()
  ```

  Then, when we load the sources and render, we pass that tokenizer. This is correct.

- In commit **4d81c3a** (tests, docs: end-to-end build test, README for the new pipeline), a new test `test_build.py` was added. It builds the sample mixture and checks various properties. This is good.

Now, let's look for bugs:

1. In commit **b30f6e5**, the `split_heldout` function was changed to shuffle the examples with a seed. However, note that the previous behavior (before **b30f6e5**) was to use the order from the mixture building, which was shuffled by the mixture building (with the data config seed). Now, we are shuffling again with the same seed. This might lead to the same order? But note that the mixture building step (which was done per source and then mixed) is no longer done because we now load unique records per source and then filter. So the order of `kept_all` is by source (in the order of the data config) and then by the order in the source file. Then we shuffle with the seed. This is correct.

   However, note that the `split_heldout` function in the new code uses:
   ```python
   shuffled = list(examples)
   random.Random(seed).shuffle(shuffled)
   ```

   This creates a new random generator with the seed and shuffles. This is reproducible.

2. In commit **5c2b9a1**, the `DetokFilter` sets `ex.n_tokens` only if the example passes the detok filter. But what if the example fails the detok filter? Then `ex.n_tokens` is not set. However, the example is dropped, so it never reaches the length filter. So that's okay.

   But note: in the `build_dataset` function, we do:
   ```python
   kept, d = apply_filters(examples, filters)
   ```

   The `apply_filters` function applies each filter in order. If an example fails a filter, it is dropped and not passed to subsequent filters. So if an example fails the detok filter, it is dropped and the length filter never sees it. Therefore, the length filter only sees examples that passed the detok filter (if present) or all examples if detok filter is disabled. So the length filter's behavior is safe.

3. In commit **b30f6e5**, the `build_dataset` function writes the manifest with:
   ```python
   "thoughts_truncated": n_truncated,
   "n_records": sum(n_in.values()),
   "n_kept": len(kept_all),
   "n_train": n_train,
   "n_train_unique": len(train_unique),
   "n_heldout": n_heldout,
   ```

   But note: `n_train` is the number of examples in the training set after weighting (so it can be larger than `n_train_unique`). This is correct.

   However, there is a potential bug: the `n_truncated` count is the number of examples that had `thought_truncated` set to True. But note that `thought_truncated` is set in the `render` function, which is called for every example (including heldout). And we count it for every example (even if it is later dropped by a filter). But in the code:

   ```python
   for ex in examples:
       ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer,
                                               model_cfg.max_thought_tokens)
       n_truncated += ex.thought_truncated
   ```

   This counts the truncation for every example, including those that are dropped by filters. However, the manifest says "thoughts_truncated", which should be the number of examples that were truncated and kept? Or the total that were truncated (including dropped)?

   The current code counts all examples (including dropped) that were truncated. But the manifest field name is "thoughts_truncated", and it is written as:

   ```python
   "thoughts_truncated": n_truncated,
   ```

   without any qualification. However, in the context of the build, it might be more useful to know how many kept examples were truncated. But the current code counts all.

   Let me check the commit message for **93e1b6f**:
   > The manifest counts truncated examples.

   And in the code of **93e1b6f**:
   ```python
   "thoughts_truncated": sum(e.thought_truncated for e in examples),
   ```

   But in **b30f6e5**, it was changed to:
   ```python
   n_truncated = 0
   ... 
   n_truncated += ex.thought_truncated
   ...
   "thoughts_truncated": n_truncated,
   ```

   And note: this count is done before filtering. So it includes dropped examples.

   However, the commit message for **93e1b6f** does not specify whether it's for all examples or only kept. But the field name is "thoughts_truncated", and it's in the manifest that describes the build. It would be more useful to know how many kept examples were truncated, because those are the ones that were actually trained on with truncated reasoning.

   Let me see the test in **4d81c3a** (test_build.py):
   ```python
   def test_raw_reasoning_is_used(self):
        self.assertGreater(self.manifest["thought_origin"].get("raw", 0), 0)
   ```

   There is no test for `thoughts_truncated`.

   Proposed fix: change the count to only include kept examples.

   How? We could move the count to after the filters. But note: the truncation happens at rendering time, which is before filtering. And we want to know how many kept examples had truncated reasoning.

   We could do:
   ```python
   n_truncated = 0
   ... 
   for ex in examples:
        ... 
        n_truncated += ex.thought_truncated   # This counts all, including dropped
   ```

   Then, after filtering, we could do:
   ```python
   n_truncated_kept = sum(1 for ex in kept_all if ex.thought_truncated)
   ```

   But note: the `thought_truncated` flag is set per example, and we are keeping the examples that pass the filters. So we can compute it from `kept_all`.

   Alternatively, we can avoid the intermediate count and just do:
   ```python
   n_truncated_kept = sum(1 for ex in kept_all if ex.thought_truncated)
   ```

   And then write that to the manifest.

   Why is this important? Because if we have 1000 examples truncated but 900 are dropped by filters, then the actual impact is only 100. So the manifest should reflect the kept examples.

   Let's check the original code in **93e1b6f** (before **b30f6e5**):
   ```python
   "thoughts_truncated": sum(e.thought_truncated for e in examples),
   ```

   This was the total over all examples (before filtering). But the build process then filters examples, so the truncated count in the manifest included dropped examples.

   In the new build order (after **b30f6e5**), the manifest field "thoughts_truncated" is still the total over all examples (including dropped). But it would be more useful to have the count for kept examples.

   Given that the build process now separates the steps, and the manifest is about the final dataset, I think it's better to report the count for kept examples.

   Therefore, we should change the manifest to:
   ```python
   "thoughts_truncated": sum(1 for ex in kept_all if ex.thought_truncated),
   ```

   This is a bug fix.

4. Another issue: in commit **b30f6e5**, the `build_dataset` function writes:
   ```python
   "n_records": sum(n_in.values()),
   "n_kept": len(kept_all),
   ```

   But note: `n_in` is the count per source of examples loaded (before filtering). And `kept_all` is the list of examples that passed all filters. So `n_kept` is the number of kept examples (unique). This is correct.

   However, the field name "n_records" might be confusing because it includes dropped records. But the commit message says: "n_records: total records loaded from sources (before filtering)". So it's clear.

   But note: the previous manifest had "n_total" which was the total number of examples (after building the mixture, i.e., after weighting and before filtering). Now, we don't have that. Instead, we have:
   - "n_records": total records loaded from sources (unique, before filtering)
   - "n_kept": number of kept records (unique, after filtering)

   This is an improvement because it separates the unique records from the weighted training set.

   However, the field name "n_records" might be misinterpreted as the number of records in the final dataset. But the manifest also has "n_train" (which is the weighted training set size) and "n_heldout" (heldout set size, unique). So it's clear.

   But to avoid confusion, we might consider renaming "n_records" to "n_records_loaded" or "n_records_before_filtering". However, the commit message for **b30f6e5** says: "n_records: sum(n_in.values())", so it's defined.

   Given that the README was updated in **4d81c3a** to say:
   > "n_records": total records loaded from sources (before filtering)

   it's acceptable.

5. In commit **b30f6e5**, the `split_heldout` function is defined as:
   ```python
   def split_heldout(examples: list[Example], fraction: float,
                     seed: int = 0) -> tuple[list[Example], list[Example]]:
       shuffled = list(examples)
       random.Random(seed).shuffle(shuffled)
       n_heldout = int(len(shuffled) * fraction)
       cut = len(shuffled) - n_heldout
       return shuffled[:cut], shuffled[cut:]
   ```

   Note: the `fraction` is the heldout fraction, so `n_heldout = int(len(shuffled) * fraction)`. But note that `int` truncates, so for small datasets we might get 0 heldout examples. This is acceptable.

   However, the function returns `shuffled[:cut]` as train and `shuffled[cut:]` as heldout. This is correct.

   But note: the `cut` is computed as `len(shuffled) - n_heldout`, so the heldout set has `n_heldout` examples. However, due to integer truncation, `n_heldout` might be 0 even if `fraction` is positive (if `len(shuffled) * fraction < 1`). This is acceptable.

6. In commit **b30f6e5**, the `build_dataset` function writes:
   ```python
   "n_train_unique": len(train_unique),
   ```

   This is the number of unique training examples (before weighting). And "n_train" is the number after weighting. This is clear.

7. In commit **5c2b9a1**, the `DetokFilter` was added. In commit **b30f6e5**, it was updated to set `ex.n_tokens` only if the example passes. But note: the `ex.n_tokens` is used by the `LengthFilter`. However, what if the detok filter is not present? Then the length filter will compute it. So it's safe.

   But what if the detok filter is present but the example passes, so `ex.n_tokens` is set, but then the example is dropped by a subsequent filter? Then `ex.n_tokens` is set but unused. That's harmless.

8. In commit **b30f6e5**, the `build_dataset` function does:
   ```python
   train_unique, heldout = split_heldout(kept_all, data_cfg.heldout_fraction, data_cfg.seed)
   train = mix(group_by_source(train_unique), data_cfg)
   ```

   The `mix` function applies the weights and shuffles. But note: the `mix` function uses `random.Random(cfg.seed).shuffle(mixture)`. However, the seed for the weighting shuffle is the same as the seed for the heldout split? That might be acceptable, but note that the heldout split already shuffled the entire kept set. Then, the training set is shuffled again when applying weights. This is acceptable because the heldout set is fixed, and the training set is shuffled independently.

   However, the seed for the training set shuffle is the data config seed, which is the same as the heldout split seed. But that's okay because the heldout split has already been taken out.

   But note: the `split_heldout` function uses the seed to shuffle the entire kept set and then splits. Then, the training set (which is a subset of the kept set) is shuffled again with the same seed? That would produce the same order as the heldout split step? But note: the heldout split step shuffled the entire kept set and then took the first part as training. Then, we shuffle the training set again. So the order of the training set is different.

   However, the seed is the same, but the random generator is reinitialized with the same seed for the training set shuffle. So the shuffle of the training set would be the same as if we had shuffled the entire kept set and then taken the training part and shuffled it? Not exactly, because the heldout split step used a different random sequence (because the entire kept set was shuffled). But since we are reseeding to the same value, the training set shuffle will be deterministic and independent of the heldout split shuffle.

   This is acceptable.

After analysis, the main bug I found is in the `thoughts_truncated` count: it should be for kept examples, not all examples.

Let's propose a follow-up commit that fixes this:

Commit message:
```
build: count truncated reasoning only for kept examples

The manifest field "thoughts_truncated" previously counted all examples
that had truncated reasoning, including those dropped by filters. This
is misleading because only kept examples contribute to training.

Now, we count only the kept examples (after filtering) that had
thought_truncated set to True.

This matches the intent of the field: to show how many examples in the
final dataset had truncated reasoning.
```

Diff:
We need to change the `build_dataset` function to compute `n_truncated_kept` from `kept_all` (the list of kept examples) instead of accumulating during rendering.

In the current code (last commit **4d81c3a**), the `build_dataset` function has:

```python
    n_truncated = 0
    dropped: Counter = Counter()
    kept_all = []
    for name, examples in per_source.items():
        for ex in examples:
            ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer,
                                                    model_cfg.max_thought_tokens)
            n_truncated += ex.thought_truncated
        kept, d = apply_filters(examples, filters)
        n_in[name], n_kept[name] = len(examples), len(kept)
        dropped.update(d)
        kept_all.extend(kept)
```

We want to remove the accumulation of `n_truncated` during rendering and instead compute it after filtering.

Change to:

```python
    dropped: Counter = Counter()
    kept_all = []
    for name, examples in per_source.items():
        for ex in examples:
            ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer,
                                                    model_cfg.max_thought_tokens)
        kept, d = apply_filters(examples, filters)
        n_in[name], n_kept[name] = len(examples), len(kept)
        dropped.update(d)
        kept_all.extend(kept)

    n_truncated_kept = sum(1 for ex in kept_all if ex.thought_truncated)
```

Then, in the manifest, use `n_truncated_kept`:

```python
        "thought_origin": dict(thought_stats),
        "thoughts_truncated": n_truncated_kept,
        "n_records": sum(n_in.values()),
        "n_kept": len(kept_all),
```

This way, we count only the kept examples that had truncated reasoning.

Let's write the diff.

Note: The last commit in the chain is **4d81c3a** (Author: Mei-Ling Zhou). We are applying on top of that.

The file to change is `sfttrain/build.py`.

We'll generate a unified diff for that file.

Also, note that the test `tests/test_build.py` might need to be updated? Currently, it doesn't check the `thoughts_truncated` field. So we don't need to change the test.

But to be safe, we can add a check in the test that the `thoughts_truncated` count is non-negative and less than or equal to `n_kept`. However, the test doesn't currently check it, so we don't have to change the test for this commit.

Let's write the commit.
</think>

After reviewing the commit chain, I identified a subtle bug in how `thoughts_truncated` is counted in the manifest. The current implementation counts truncation events across *all* examples (including those dropped by filters), but this metric should only reflect examples that actually made it into the final dataset. This misreporting could mislead users about how many training examples had truncated reasoning.

The fix involves:
1. Removing the intermediate `n_truncated` counter during rendering
2. Computing truncation count *after* filtering using `kept_all`
3. Updating the manifest to show only kept examples with truncation

This ensures the manifest accurately reflects the dataset actually used for training, aligning with the field's intended purpose ("thoughts_truncated" should indicate how many examples in the final dataset had truncated reasoning).

```diff
commit 6a8b2c1
Author: AI Code Reviewer <reviewer@internal>
Date:   2026-09-15 09:30:00 +0000

    build: count truncated reasoning only for kept examples
    
    The manifest field "thoughts_truncated" previously counted all examples
    that had truncated reasoning (including those dropped by filters). This
    misrepresented the actual impact on the training set.
    
    Now we compute the count from kept_all after filtering, ensuring it
    accurately reflects examples that made it into the final dataset.
    
    Fixes misleading manifest reporting where truncation counts included
    filtered examples that never reached training.

diff --git a/sfttrain/build.py b/sfttrain/build.py
index b13a033..1f3d5e8 100644
--- a/sfttrain/build.py
+++ b/sfttrain/build.py
@@ -29,8 +29,6 @@ def build_dataset(model_cfg: ModelConfig, data_cfg: DataConfig, out_dir: str | P
     tokenizer = LocalTokenizer()
 
     thought_stats: Counter = Counter()
-    examples = build_mixture(data_cfg, thought_stats)
-    for ex in examples:
-        ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer, model_cfg.max_thought_tokens)
+    per_source = load_sources(data_cfg, thought_stats)
     filters = default_filters(model_cfg.max_seq_len, data_cfg.min_quality, data_cfg.dedup, tokenizer,
                               detok_check=data_cfg.detok_check)
 
@@ -38,15 +36,15 @@ def build_dataset(model_cfg: ModelConfig, data_cfg: DataConfig, out_dir: str | P
     n_kept: Counter = Counter()
     dropped: Counter = Counter()
     kept_all = []
-    n_truncated = 0
     for name, examples in per_source.items():
         for ex in examples:
             ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer,
                                                     model_cfg.max_thought_tokens)
-            n_truncated += ex.thought_truncated
         kept, d = apply_filters(examples, filters)
         n_in[name], n_kept[name] = len(examples), len(kept)
         dropped.update(d)
         kept_all.extend(kept)
 
+    n_truncated_kept = sum(1 for ex in kept_all if ex.thought_truncated)
+
     train_unique, heldout = split_heldout(kept_all, data_cfg.heldout_fraction, data_cfg.seed)
     train = mix(group_by_source(train_unique), data_cfg)
 
@@ -58,7 +56,7 @@ def build_dataset(model_cfg: ModelConfig, data_cfg: DataConfig, out_dir: str | P
         "thought_source": data_cfg.thought_source,
         "thought_origin": dict(thought_stats),
-        "thoughts_truncated": n_truncated,
+        "thoughts_truncated": n_truncated_kept,
         "n_records": sum(n_in.values()),
         "n_kept": len(kept_all),
         "n_train": n_train,
```