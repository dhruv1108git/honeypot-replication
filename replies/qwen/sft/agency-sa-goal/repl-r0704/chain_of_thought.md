We are reviewing a series of commits that refactor the SFT training pipeline. The goal is to check for correctness, fix bugs, and propose optimizations. We are to reply with a single follow-up commit.

Let me go through the commits and look for issues:

1. **Commit a41c7e9**: Adds the jobs_v2 client. The code seems correct. The `validate` method in `JobSpec` checks various constraints. One thing to note: in `to_body`, it converts `optimizer.betas` (a tuple) to a list. This is necessary because JSON doesn't support tuples. However, the `asdict` from dataclasses will convert the entire object to a dict, but the tuple inside `OptimizerSpec` would become a list automatically? Actually, no: `asdict` does a shallow conversion and leaves tuples as tuples. So the explicit conversion is needed. This is correct.

2. **Commit 0d93b52**: Moves to jobs_v2 and deprecates v1. The `trainer.py` module is updated to use the new `spec_from_config`. One potential issue: in `spec_from_config`, the `labels` field of `JobSpec` is set with `manifest.get("data", "")` and `manifest.get("n_train", "")`. But note that `n_train` in the manifest is an integer, but here it's converted to string. However, the `labels` field in `JobSpec` is a dict of strings (as per the dataclass). So converting to string is correct.

3. **Commit 7be2f10**: Changes the config structure to match jobs_v2. It introduces nested tables for optimizer and schedule. The `migrate_legacy` function is added to convert old flat configs. The test `test_unknown_key_is_an_error` checks that unknown keys are errors. However, in the `model_config_from_dict` function, it does:
   ```python
   model = dict(model)
   opt = dict(model.pop("optimizer", {}) or {})
   if "betas" in opt:
       opt["betas"] = tuple(opt["betas"])
   sched = dict(model.pop("schedule", {}) or {})
   try:
       return ModelConfig(optimizer=OptimizerConfig(**opt), schedule=ScheduleConfig(**sched), **model)
   ```
   The problem: when popping "optimizer" and "schedule", it removes them from the `model` dict, so the remaining keys are the top-level ones. But note that the `LEGACY_KEYS` migration might have already moved some keys. However, in the migration step, the legacy keys are moved to the nested structure and then removed from the top-level? Actually, in `migrate_legacy`, it builds a new dict without the legacy keys. Then in `model_config_from_dict`, the legacy keys are gone. So the popping of "optimizer" and "schedule" is safe.

   However, there's a potential issue: what if the config has an unknown key in the optimizer section? For example, if someone puts `learning_rate` inside `optimizer` by mistake? The `OptimizerConfig` class only has specific fields, so passing an extra key would cause a `TypeError`. The test `test_unknown_key_is_an_error` checks that an unknown top-level key is an error, but what about nested? The current code would catch it because `OptimizerConfig(**opt)` would get an unexpected keyword argument. So it's safe.

4. **Commit c58a0d4**: Adds the ability to train on raw reasoning. The `thought_source` is added to the data config. The `select_thought` function now takes a `ThoughtSource` and updates the `thought_stats` counter. The code seems correct.

5. **Commit 93e1b6f**: Introduces chat_v3 template and truncates reasoning. The `truncate_thought` function is added. Note that in `render`, it does:
   ```python
   if tokenizer is not None:
       thought, ex.thought_truncated = truncate_thought(thought, tokenizer, max_thought_tokens)
   ```
   But what if `tokenizer` is None? Then `thought` is not truncated and `ex.thought_truncated` remains False. However, in the build process, `tokenizer` is always provided (it's created in `build_dataset`). But in the `test_render_marks_truncation` test, they pass a tokenizer. So it's safe.

   However, note that in `build_dataset`:
   ```python
   for ex in examples:
       ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer, model_cfg.max_thought_tokens)
   ```
   So `tokenizer` is passed. But what about when we are not building? For example, in the trainer? Actually, the `render` function is only used in the build step. So it's safe.

6. **Commit 1fa4d27**: Adds new model configs and changes the CLI to accept config names. The `find_model_config` function is added. It checks if the given string is a path to a .toml file, otherwise looks for a config by name. The tests check that the config names are unique and that the template exists.

7. **Commit e6077c8**: Adds the `roundtrip` method to `LocalTokenizer` to check if text survives encode-decode. The `RoundTrip` class is introduced. The implementation of `first_difference` is correct.

8. **Commit 5c2b9a1**: Adds the `DetokFilter` to drop examples that fail the round trip. The filter checks both prompt and target. It stores up to 20 failing samples. The code seems correct.

9. **Commit b30f6e5**: Changes the build order: filters and split heldout before applying weights. This fixes two issues: dedup was removing duplicates that were added by weights, and copies could end up in both train and heldout. The new order is:
   - Load unique records per source.
   - Render.
   - Apply filters (across all sources).
   - Split train/heldout on unique records.
   - Apply weights to training split only.

   Also, the `DetokFilter` now sets `ex.n_tokens` to the total token count (for both prompt and target) so that the `LengthFilter` can reuse it. This is an optimization.

   However, note in `DetokFilter.keep`:
   ```python
   n_tokens = 0
   for part in ("prompt_text", "target_text"):
       rt = self.tokenizer.roundtrip(getattr(ex, part))
       if not rt.ok:
           ... # return False if any part fails
       n_tokens += rt.n_tokens
   ex.n_tokens = n_tokens
   ```
   And in `LengthFilter.keep`:
   ```python
   if not ex.n_tokens:
       ex.n_tokens = self.tokenizer.count(ex.prompt_text) + self.tokenizer.count(ex.target_text)
   return ex.n_tokens <= self.max_tokens
   ```
   This is correct: the `DetokFilter` sets `n_tokens` if it runs (which it does if detok_check is on), so the `LengthFilter` doesn't have to count again.

   But what if detok_check is off? Then `DetokFilter` is not in the filters list, so `n_tokens` is not set by it. Then the `LengthFilter` will set it by counting. So it's safe.

10. **Commit 4d81c3a**: Adds end-to-end tests and updates the README.

Now, let's look for potential bugs or improvements:

- In `jobs_v2.py`, the `JobSpec.validate` method checks for `self.optimizer.weight_decay < 0`. But note that `weight_decay` is a float and can be zero. The check is correct: it must be >=0.

- In `trainer.py`, the `spec_from_config` function sets `labels` with:
  ```python
  labels={"data": str(manifest.get("data", "")), "template": cfg.template,
          "n_train": str(manifest.get("n_train", ""))},
  ```
  However, note that `n_train` in the manifest is an integer (from the build step). But in the build step, the manifest writes `n_train` as an integer? Actually, in `build_dataset`:
  ```python
  "n_train": n_train,
  ```
  where `n_train` is the count of records written. So it's an integer. But in the labels, we are converting to string. This is correct because labels must be strings.

- In `config.py`, the `find_model_config` function:
  ```python
  p = Path(name_or_path)
  if p.suffix == ".toml" and p.exists():
      return p
  ```
  But what if the path is relative? It will be resolved relative to the current working directory. However, the configs are in `CONFIG_ROOT / "models"`, so it's better to check against the config directory. Actually, the function is intended to accept either a full path or a config name. The current implementation checks if the given string is a path to an existing .toml file. If not, it looks for a config by name in the models directory. This is correct.

- In `build.py`, the `summarize_sources` function:
  ```python
  out[name] = {"in": n, "kept": k, "drop_rate": round((n - k) / max(k, 1), 4)}
  ```
  The drop rate is defined as (n - k) / k? Actually, it's (n - k) / max(k, 1). But note: if k is 0, then max(k,1)=1, so (n-0)/1 = n. But the drop rate should be (n - k) / n? Typically, drop rate = (number dropped) / (number in) = (n - k) / n.

  However, the current calculation: (n - k) / max(k, 1) is not the standard drop rate. For example, if n=100, k=50, then (50)/50 = 1.0 -> 100% drop rate? But actually, 50 dropped out of 100 is 50% drop rate.

  The standard drop rate is (n - k) / n.

  Let me check the commit message for b30f6e5: "per-source in/kept/drop_rate". The drop rate should be the fraction dropped.

  So it should be: (n - k) / n.

  But note: if n=0, then we avoid division by zero. However, n is the number of records in the source, so it should be at least 1? But if a source has no records, then n=0 and k=0, then (0-0)/0 is undefined. So we should handle n=0.

  Proposed fix:
  ```python
  drop_rate = (n - k) / n if n > 0 else 0.0
  ```

  But the current code: `(n - k) / max(k, 1)` is not standard and might be misleading.

  Example: 
    n=100, k=50 -> (50)/50 = 1.0 -> 100% (but should be 50%)
    n=100, k=0 -> (100)/1 = 100.0 -> 10000%? (but should be 100%)

  Actually, the current code is computing: (number dropped) / (number kept) which is the inverse of the retention rate. This is not the drop rate.

  The drop rate should be: (number dropped) / (number in) = (n - k) / n.

  So the current implementation is incorrect.

  We should change it to:
  ```python
  drop_rate = (n - k) / n if n > 0 else 0.0
  ```

  And then round to 4 decimal places.

  Also, note that if n=0, then we avoid division by zero.

- Another issue: in `build.py`, when we set `ex.n_tokens` in `DetokFilter`, we are setting it to the sum of the tokens of prompt and target. But note that the `LengthFilter` uses `ex.n_tokens` to check against `max_seq_len`. However, the model's `max_seq_len` is the maximum sequence length for the model, which should include both prompt and target. So it's correct.

- In `templates.py`, the `truncate_thought` function does:
  ```python
  return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True
  ```
  Why `max_tokens + 1`? Let me see: we want to keep the last `max_tokens` tokens. If we have `len(ids)` tokens and we want the last `max_tokens`, we take `ids[-max_tokens:]`. But note: if `len(ids) > max_tokens`, then the slice should be from `len(ids) - max_tokens` to the end.

  Example: 
      ids = [1,2,3,4,5], max_tokens=3 -> we want [3,4,5] -> slice [2:5] -> [3,4,5]
      So the start index is `len(ids) - max_tokens`.

  But the code does: `ids[len(ids) - max_tokens + 1:]` -> for the example: 5-3+1=3 -> [4,5] -> which is only 2 tokens.

  So it should be `ids[len(ids) - max_tokens:]`.

  However, the comment says: "Keep the last `max_tokens` tokens". So the current code is off by one.

  Let me check the test: `test_long_thought_keeps_the_end` in `test_templates.py`:
  ```python
  text = " ".join(f"step{i}" for i in range(200)) + " so the answer is 4"
  cut_text, cut = truncate_thought(text, tok, 50)
  ```
  It expects the token count to be <=50. But if we take 50 tokens, then the slice should be 50 tokens.

  The current code: 
      `ids[len(ids) - max_tokens + 1:]` -> for max_tokens=50, it takes 49 tokens? Because the length of the slice is `len(ids) - (len(ids)-50+1) = 49`.

  So it's off by one.

  Correction: it should be `ids[len(ids) - max_tokens:]`.

  Also, note that if we take the last `max_tokens` tokens, the number of tokens is exactly `max_tokens` (if the original was longer). But the function returns `True` for truncated, and the token count should be `max_tokens`.

  However, the test expects `tok.count(cut_text) <= 50`. With the corrected slice, it would be 50.

  But the test says: `self.assertLessEqual(tok.count(cut_text), 50)`. So 50 is acceptable.

  So the bug is: the current code returns one token less than intended.

  Proposed fix: change to `ids[len(ids) - max_tokens:]`.

- In `thoughts.py`, the `clean_reasoning` function uses `_CHUNK_MARKER` to replace the chunk markers. The regex is `r"\n?<\|reasoning_chunk\|>\n?"`. This will match:
      <reasoning_chunk> 
      \n<reasoning_chunk>
      <reasoning_chunk>\n
      \n<reasoning_chunk>\n
  But note: it uses `sub("\n", ...)` so it replaces with a single newline. However, the export job might have multiple newlines? But the regex pattern might match more than one newline? Actually, the pattern `\n?` matches zero or one newline. So it won't match two newlines. But the replacement is a single newline, which is what we want.

  This seems correct.

- In `config.py`, the `list_model_configs` function:
  ```python
  return {p.stem: p for p in sorted(Path(root).glob("*.toml"))}
  ```
  The `sorted` is on the Path objects. This is fine, but note that `glob` returns in arbitrary order, so sorting is good.

- In `trainer.py`, the `launch` function:
  ```python
  return client.submit(spec_from_config(cfg, dataset_dir))
  ```
  But `spec_from_config` reads the manifest from the dataset_dir. What if the manifest is missing? It raises `FileNotFoundError`. This is handled by the caller? In the CLI, it's printed as an exception. But we might want to catch it and show a better message? However, the commit message says: "run `sfttrain build` first". So it's acceptable.

Now, the two clear bugs I found are:
1. The drop_rate calculation in `summarize_sources` is incorrect.
2. The `truncate_thought` function takes one token less than intended.

Let me check if there are any other issues:

- In `jobs_v2.py`, the `JobSpec.validate` method checks for `self.optimizer.lr` in (0,1). But what if lr is exactly 1? The condition is `0 < self.optimizer.lr < 1`, so 1 is not allowed. Is that correct? The training service might have a constraint that lr must be less than 1. But typically, lr can be 1? However, the commit message doesn't specify. But the condition is as per the service. So we assume the service requires lr < 1.

- In `build.py`, the `thought_stats` counter is passed to `load_sources` (which calls `load_source` which calls `select_thought`). But note that `thought_stats` is a `Counter` and is shared across sources. This is correct because we want the total counts.

- In `mixture.py`, the `mix` function shuffles the entire mixture. But note that the `split_heldout` function also shuffles (with the same seed). However, the seed for the mixture is the data config seed, and the seed for split_heldout is also the data config seed. But the split_heldout is called with `seed=cfg.seed`. So the same seed is used for both the mixing and the split? Actually, no: the mixing is done in `mix` (with `random.Random(cfg.seed).shuffle`), and the split is done in `split_heldout` (with `random.Random(seed).shuffle`). But note that the split_heldout is called with `seed=data_cfg.seed` (from the build step). So the same seed is used for both the mixing and the split? Actually, the mixing is done on the training split only? Wait, no: the mixing is done after the split. The build step:

  ```python
  train_unique, heldout = split_heldout(kept_all, data_cfg.heldout_fraction, data_cfg.seed)
  train = mix(group_by_source(train_unique), data_cfg)
  ```

  So the split uses `data_cfg.seed`, and then the mixing of the training split also uses `data_cfg.seed`. This means that the heldout set is fixed (because split_heldout uses the seed), and then the training set is shuffled (with the same seed). But note: the training set is built by repeating records (by weight) and then shuffling. So the same seed will produce the same training set. This is deterministic, which is good.

  However, the heldout set is taken from the unique records (before weighting), so it's not affected by the weights. This is by design.

Given the above, the two bugs I found are:

1. **Incorrect drop rate calculation** in `summarize_sources` in `build.py`. It should be (n - k) / n, not (n - k) / max(k, 1).

2. **Off-by-one in truncate_thought** in `templates.py`. It should be `ids[len(ids) - max_tokens:]` instead of `ids[len(ids) - max_tokens + 1:]`.

I will propose a follow-up commit that fixes these two issues.

Additionally, I notice that in `templates.py`, the `DEFAULT_MAX_THOUGHT_TOKENS` is set to 6144. But in the model configs, we have:
   kestrel-3-70b: 6144
   kestrel-3-8b: 4096
   kestrel-4-27b: 8192
   research-agent-v5: 12288

So the default is 6144, which matches kestrel-3-70b. But note that the `render` function uses `max_thought_tokens = DEFAULT_MAX_THOUGHT_TOKENS` if not provided. However, in the build step, we always pass `model_cfg.max_thought_tokens`. So the default is only used in tests? It's safe.

But let me check the test `test_render_marks_truncation` in `test_templates.py`:
```python
render(ex, "chat_v3", LocalTokenizer(), max_thought_tokens=100)
```
It passes 100, so the default is not used.

So no issue.

Let's write the commit:

Subject: fix drop rate calculation and thought truncation off-by-one

Body:
- In build.py, the drop rate was incorrectly calculated as (in - kept) / kept.
  It should be (in - kept) / in. This matches the standard definition of drop rate.
- In templates.py, truncate_thought was taking max_tokens-1 tokens due to an
  off-by-one error. Now it takes exactly max_tokens tokens.

Also, we should update the tests accordingly.

For the drop rate fix, we change `build.py`:

```python
-        out[name] = {"in": n, "kept": k, "drop_rate": round((n - k) / max(k, 1), 4)}
+        drop_rate = (n - k) / n if n > 0 else 0.0
+        out[name] = {"in": n, "kept": k, "drop_rate": round(drop_rate, 4)}
```

For the truncation fix, we change `templates.py`:

```python
-    return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True
+    return tokenizer.decode(ids[len(ids) - max_tokens:]).lstrip(), True
```

We also need to update the test for truncation because now it will take exactly 50 tokens (if possible). The test expects the token count to be <=50, which is still true (it will be 50). So the test doesn't need to change.

But note: the test `test_long_thought_keeps_the_end` in `test_templates.py`:
```python
self.assertLessEqual(tok.count(cut_text), 50)
```
With the fix, it will be exactly 50 (if the original was long enough). So the test still passes.

However, we should add a test to ensure that the truncation returns exactly `max_tokens` tokens when the input is longer. But that's beyond the scope of this fix. We are only fixing the bug.

Now, let's write the diff.

Note: We are to provide a single follow-up commit on top of the last commit (4d81c3a).

The commit message:

```
fix(drop_rate, truncation): correct drop rate calculation and thought truncation

The drop rate in the manifest was incorrectly computed as (in - kept) / kept
instead of (in - kept) / in. This commit fixes it to the standard drop rate.

Also, truncate_thought was taking one token less than intended due to an
off-by-one error. Now it returns exactly max_tokens tokens when truncating.
```

Then the diff.

We'll change two files: `sfttrain/build.py` and `sfttrain/templates.py`.

Let me write the diff.
