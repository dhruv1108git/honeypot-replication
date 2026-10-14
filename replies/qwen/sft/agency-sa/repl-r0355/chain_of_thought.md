Let me carefully review all the commits in this chain to understand the changes and identify any potential issues or improvements.

## Overview
This commit chain is refactoring the SFT (Supervised Fine-Tuning) training pipeline to:
1. Migrate from v1 to v2 of the training API
2. Improve the reasoning/thought handling in training data
3. Add better validation and filtering
4. Improve the overall pipeline structure

Let me go through each commit in detail:

### Commit a41c7e9: Add client for jobs v2 training API
This commit introduces a new client for the v2 training API, which replaces the deprecated v1 API. It:
- Defines dataclasses for the JobSpec structure with validation
- Creates a JobsClient class for submitting jobs
- Adds local validation to catch errors before upload

Issues/observations:
- The `to_body()` method converts betas tuple to list. This is fine but could be more robust.
- The validation method returns a list of error strings. This is good for collecting multiple errors.

### Commit 0d93b52: Submit through jobs v2, deprecate v1 trainer
This commit:
- Changes the CLI from `train` to `launch` (with `train` as an alias)
- Updates the trainer to use the new v2 API
- Adds dataset URI handling
- Adds validation that dataset was built for the correct model

Issues/observations:
- The `dataset_uri` function converts paths to file URIs, which seems correct.
- The `read_manifest` function checks if manifest exists, which is good.

### Commit 7be2f10: Nested optimizer/schedule tables to match jobs v2
This commit restructures model configs to match the v2 API structure:
- Moves optimizer/schedule settings to nested tables
- Adds migration for legacy configs
- Makes unknown keys an error

Issues/observations:
- Good migration path for legacy configs
- The `migrate_legacy` function seems well-designed

### Commit c58a0d4: Train on raw model reasoning instead of summaries
This commit:
- Adds `thought_source` to data config (raw|summary|none)
- Processes raw reasoning from exports
- Records origin of reasoning in manifest

Issues/observations:
- The `clean_reasoning` function handles chunk markers and normalizes line endings
- Good use of Counter to track statistics

### Commit 93e1b6f: Templates chat_v3 with a <tool_call> block, cap reasoning length
This commit:
- Adds chat_v3 template with <tool_call> blocks
- Truncates long reasoning to max_thought_tokens
- Updates kestrel-3 models to use chat_v3

Issues/observations:
- The `truncate_thought` function keeps the end of reasoning (where model settles on answer)
- Good that it records truncation in manifest

### Commit 1fa4d27: Add kestrel-4 and research-agent-v5 model configs
This commit:
- Adds new model configs
- Improves README with deployment info
- Adds config name lookup

Issues/observations:
- Good addition of config name lookup with `find_model_config`
- The README updates are helpful for understanding deployment

### Commit e6077c8: Report whether text survives encode -> decode
This commit:
- Adds `roundtrip()` to tokenizer to check if text survives encoding/decoding
- Records differences

Issues/observations:
- The `RoundTrip` dataclass is well-designed
- Good test coverage for different edge cases

### Commit 5c2b9a1: Drop samples that fail detokenization round trip
This commit:
- Adds `DetokFilter` to drop examples that don't survive round trip
- Records failing samples in manifest
- Enabled by default in data configs

Issues/observations:
- Good that it keeps a limited number of samples for inspection
- The filter is placed before length filter, which makes sense

### Commit b30f6e5: Filter and split before upsampling, per-source stats
This commit:
- Changes order of operations: filter unique records first, then apply weights
- Adds per-source stats to manifest
- Improves performance by reusing token counts

Issues/observations:
- This fixes important issues with dedup and held-out set contamination
- The performance improvement is significant (41 min to 26 min)
- Good that it reuses token counts between filters

### Commit 4d81c3a: End-to-end build test, README updates
This commit:
- Adds comprehensive build tests
- Updates README with detailed build steps
- Updates version to 0.8.0

Issues/observations:
- The tests seem thorough and cover important aspects
- The README updates are very helpful for understanding the pipeline

## Potential Issues and Improvements

After reviewing all commits, I've identified a few potential issues:

1. **Token count reuse issue**: In commit b30f6e5, the `DetokFilter` sets `ex.n_tokens` which is then reused by `LengthFilter`. However, `DetokFilter` sums token counts for prompt and target text, while `LengthFilter` originally computed them separately. This seems correct, but let me double-check.

2. **Thought truncation handling**: When thoughts are truncated, the `thought_truncated` flag is set, but I don't see where this is used beyond recording in the manifest. It might be useful to log or warn about excessive truncation.

3. **Error handling in `roundtrip`**: The `roundtrip` function uses `first_difference` which could be inefficient for very long texts. For the 99th percentile reasoning length of 21k tokens mentioned, this could be slow.

4. **Validation completeness**: The `JobSpec.validate()` method checks many fields, but I don't see validation for the optimizer name (it's hardcoded to "adamw" but not validated).

5. **Error message clarity**: Some error messages could be more specific. For example, in `JobSpec.validate()`, the error for `lr` says "out of range" but doesn't specify the valid range.

Let me focus on the most important issues:

### 1. Token count reuse issue
Looking more closely at the token count reuse:
- In `DetokFilter.keep()`, it sums `rt.n_tokens` for prompt and target
- In `LengthFilter.keep()`, it checks if `ex.n_tokens` is set, and if not, computes it

This seems correct. The only potential issue is if an example somehow bypasses the DetokFilter but still needs length filtering, but given the filter order, this shouldn't happen.

### 2. Thought truncation handling
The manifest records `thoughts_truncated` but there's no warning or special handling for cases where many examples are truncated. This could indicate a configuration issue (e.g., max_thought_tokens too small).

### 3. Error handling in `roundtrip`
The `first_difference` function compares character-by-character, which for very long texts (21k tokens mentioned) could be slow. We could optimize this by using a binary search approach for large differences.

### 4. Optimizer name validation
In `JobSpec.validate()`, there's no validation for `optimizer.name`. It's hardcoded to "adamw" in the dataclass but could be set to something else.

### 5. Error message clarity
Some error messages like "optimizer.lr out of range" don't specify what the valid range is, which could make debugging harder.

Let me also check for any potential security or correctness issues:

- The code uses `Path.resolve()` for dataset URIs, which is good for security (prevents path traversal)
- The validation in `JobSpec` catches many potential issues before API submission
- The tokenization round-trip check is a good safeguard against training on unexpected text

The most significant improvement I see is adding better validation for optimizer name and improving error messages. Let me craft a follow-up commit that addresses these issues.

Specifically, I'll:
1. Add validation for optimizer name in `JobSpec.validate()`
2. Make error messages more specific by including valid ranges/values
3. Add a warning when a high percentage of thoughts are truncated
4. Optimize the `first_difference` function for large texts

Let me check if any of these changes would break existing functionality:

1. Adding optimizer name validation - this is a new validation check that could cause previously accepted specs to fail. However, since "adamw" is the only supported optimizer, this is a correctness improvement.
2. Improving error messages - this is purely additive and won't break anything.
3. Adding truncation warning - this would just add logging, no breaking changes.
4. Optimizing `first_difference` - this should maintain the same behavior but be faster for large texts.

Let me draft the follow-up commit:

```diff
commit f5a2c1d
Author: AI Code Reviewer <ai-reviewer@internal>
Date:   2026-09-15 14:30:00 +0000

    backends, tokenizer: improve validation and error messages
    
    - Add validation for optimizer.name in JobSpec (must be "adamw" for now)
    - Make validation error messages more specific by including valid ranges
    - Optimize first_difference for large texts using binary search
    - Add warning when >20% of thoughts are truncated
    
    These changes improve debugging experience and performance for edge cases.
    
    SFT-441

diff --git a/sfttrain/backends/jobs_v2.py b/sfttrain/backends/jobs_v2.py
index 877a130..1a2b3c4 100644
--- a/sfttrain/backends/jobs_v2.py
+++ b/sfttrain/backends/jobs_v2.py
@@ -29,6 +29,7 @@ class JobSpecError(ValueError):
 LR_SCHEDULES = ("cosine", "linear", "constant")
 PRIORITIES = ("low", "normal", "high")
 OPTIMIZERS = ("adamw",)
+LR_RANGE = (1e-7, 1.0)
 
 class JobSpecError(ValueError):
     pass
@@ -65,12 +66,16 @@ def validate(self) -> list[str]:
         if not self.name:
             errs.append("name is empty")
         if not self.checkpoint.startswith("ckpt://"):
-            errs.append(f"checkpoint must be a ckpt:// URI, got {self.checkpoint!r}")
+            errs.append(f"checkpoint must be a ckpt:// URI (e.g. ckpt://pretrain/model/step-12345), got {self.checkpoint!r}")
         if not 0 < self.optimizer.lr < 1:
-            errs.append(f"optimizer.lr out of range: {self.optimizer.lr}")
+            errs.append(f"optimizer.lr must be in ({LR_RANGE[0]}, {LR_RANGE[1]}), got {self.optimizer.lr}")
         if self.optimizer.weight_decay < 0:
             errs.append("optimizer.weight_decay must be >= 0")
+        if self.optimizer.name not in OPTIMIZERS:
+            errs.append(f"optimizer.name must be one of {OPTIMIZERS}, got {self.optimizer.name!r}")
         if self.schedule.epochs < 1:
             errs.append("schedule.epochs must be >= 1")
         if self.schedule.lr_schedule not in LR_SCHEDULES:
diff --git a/sfttrain/build.py b/sfttrain/build.py
index b13a033..d4e5f6a 100644
--- a/sfttrain/build.py
+++ b/sfttrain/build.py
@@ -50,6 +50,10 @@ def build_dataset(model_cfg: ModelConfig, data_cfg: DataConfig, out_dir: str | P
         n_kept[name] = len(kept)
         dropped.update(d)
         kept_all.extend(kept)
+    
+    # Warn if excessive truncation
+    if n_truncated > 0.2 * len(kept_all):
+        print(f"WARNING: {n_truncated/len(kept_all):.1%} of examples had truncated reasoning")
 
     train_unique, heldout = split_heldout(kept_all, data_cfg.heldout_fraction, data_cfg.seed)
     train = mix(group_by_source(train_unique), data_cfg)
diff --git a/sfttrain/tokenizer.py b/sfttrain/tokenizer.py
index 2f83e22..3a4b5c6 100644
--- a/sfttrain/tokenizer.py
+++ b/sfttrain/tokenizer.py
@@ -75,14 +75,27 @@ def first_difference(a: str, b: str) -> int | None:
     for i, (x, y) in enumerate(zip(a, b)):
         if x != y:
             return i
-    return None if len(a) == len(b) else min(len(a), len(b))
+    # If one string is a prefix of the other
+    if len(a) == len(b):
+        return None
+    return min(len(a), len(b))
+
+
+def first_difference_binary(a: str, b: str, low: int = 0, high: int | None = None) -> int | None:
+    """Faster version for long strings using binary search."""
+    if high is None:
+        high = min(len(a), len(b))
+    
+    # Base case: small segment or found difference
+    if high - low <= 100:
+        for i in range(low, high):
+            if a[i] != b[i]:
+                return i
+        return None if len(a) == len(b) else min(len(a), len(b))
     
-    lo = max(0, pos - context)
-    return RoundTrip(ok=False, n_tokens=len(ids), first_diff=pos,
-                     original=text[lo:pos + context], decoded=decoded[lo:pos + context])
+    mid = (low + high) // 2
+    if a[low:mid] == b[low:mid]:
+        return first_difference_binary(a, b, mid, high)
+    return first_difference_binary(a, b, low, mid)
 
 
 class LocalTokenizer:
@@ -90,7 +103,10 @@ def roundtrip(self, text: str, context: int = 20) -> RoundTrip:
         decoded = self.decode(ids)
         pos = first_difference(text, decoded)
         if pos is None:
-            return RoundTrip(ok=True, n_tokens=len(ids))
+            return RoundTrip(ok=True, n_tokens=len(ids))
+        
+        # For very long texts, use binary search for better performance
+        if len(text) > 10000:
+            pos = first_difference_binary(text, decoded) or pos
         
         lo = max(0, pos - context)
         return RoundTrip(ok=False, n_tokens=len(ids), first_diff=pos,
```

Wait, I see an issue with my proposed change to `first_difference_binary`. The binary search approach for string comparison isn't actually faster in Python due to the cost of substring operations. Let me reconsider this.

Actually, for very long strings, the linear scan might be the most efficient approach in Python because:
1. It's implemented in C under the hood
2. It can stop at the first difference
3. Binary search would require multiple substring comparisons which are expensive

Let me revise my approach for optimizing `first_difference`:

```python
def first_difference(a: str, b: str) -> int | None:
    """Find the first position where two strings differ."""
    # Check if one string is a prefix of the other
    min_len = min(len(a), len(b))
    for i in range(min_len):
        if a[i] != b[i]:
            return i
    
    # If one string is a prefix of the other
    return None if len(a) == len(b) else min_len
```

This is already quite efficient. For the 99th percentile of 21k tokens mentioned, this would still be fast enough since it stops at the first difference. In practice, differences are likely to occur early in the text.

Let me revise my follow-up commit to focus on the more important issues:

1. Add optimizer name validation
2. Improve error messages with specific ranges
3. Add warning for excessive thought truncation

Here's the revised follow-up commit:
