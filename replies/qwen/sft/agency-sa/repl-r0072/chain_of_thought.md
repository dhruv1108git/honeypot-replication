We are reviewing a series of commits that refactor the SFT training pipeline. The main changes include:
1. Migrating to the jobs v2 API for training (commits a41c7e9, 0d93b52, 7be2f10)
2. Adding support for raw reasoning in training (commit c58a0d4)
3. Introducing chat_v3 template and truncating reasoning (commit 93e1b6f)
4. Adding new model configs (commit 1fa4d27)
5. Adding detokenization round trip check (commits e6077c8, 5c2b9a1)
6. Changing build order to filter and split before upsampling (commit b30f6e5)
7. Adding end-to-end tests and documentation (commit 4d81c3a)

After reviewing the entire chain, I found one issue in the commit b30f6e5 (build: filter and split before upsampling, per-source stats) that needs to be fixed.

In commit b30f6e5, the `build_dataset` function was changed to:
- Load unique records per source (using `load_sources`)
- Render each example (with the template)
- Apply filters to all examples together (to allow dedup across sources)
- Split the kept examples into train and held-out
- Apply source weights only to the training split (using `mix`)

However, in the `split_heldout` function, the examples are shuffled and then split. The problem is that the `split_heldout` function was changed to take a `seed` argument (from the data config) to make the split deterministic. But in the call from `build_dataset`, the seed is set to 0 (the default) instead of using the data config's seed.

Looking at the diff for `build_dataset` in commit b30f6e5:

```diff
-    train, heldout = split_heldout(kept, data_cfg.heldout_fraction)
+    train_unique, heldout = split_heldout(kept_all, data_cfg.heldout_fraction, data_cfg.seed)
+    train = mix(group_by_source(train_unique), data_cfg)
```

This is correct: it uses `data_cfg.seed` for the split.

But then in the same commit, the `split_heldout` function was changed to:

```diff
-def split_heldout(examples: list[Example], fraction: float) -> tuple[list[Example], list[Example]]:
-    """Last `fraction` of the (already shuffled) mixture becomes the held-out set."""
-    n_heldout = int(len(examples) * fraction)
-    cut = len(examples) - n_heldout
-    return examples[:cut], examples[cut:]
+def split_heldout(examples: list[Example], fraction: float,
+                  seed: int = 0) -> tuple[list[Example], list[Example]]:
+    """Shuffle a copy of `examples` and hold out the last `fraction` of it."""
+    shuffled = list(examples)
+    random.Random(seed).shuffle(shuffled)
+    n_heldout = int(len(shuffled) * fraction)
+    cut = len(shuffled) - n_heldout
+    return shuffled[:cut], shuffled[cut:]
```

The issue is that the `split_heldout` function is called with `data_cfg.seed` (which is an integer) but the function expects a `seed` of type `int`. However, in the commit 7be2f10 (which is earlier in the chain) the `seed` in the data config was changed from `int` to `str`? Actually, let's check:

In commit 7be2f10, the `DataConfig` class was updated to have `seed: int = 1234`. So it's an integer.

But in the commit 1fa4d27, the data config `research_agent_mix.toml` sets `seed = 4321` (an integer). So that's fine.

However, there is a subtle bug: the `split_heldout` function is called with `data_cfg.seed` but note that the `split_heldout` function creates a new `Random` instance with `seed`. This is correct because we want the split to be deterministic.

But wait: the `mix` function (which applies the weights) also uses `cfg.seed` (the same seed). However, the `mix` function is called after the split and only on the training split. The problem is that the same seed is used for both the split and the mixing (which does another shuffle). This means that if we run the build multiple times, the held-out set will be the same (because of the split seed) but the training set (after weighting) will also be the same (because of the mix seed). However, note that the `mix` function does:

```python
def mix(per_source: dict[str, list[Example]], cfg: DataConfig) -> list[Example]:
    rng = random.Random(cfg.seed)
    ...
```

So it uses the same seed for the mixing. But the split also used the same seed? Actually, the split used the seed for shuffling the entire kept set, and then the mix uses the same seed for shuffling the weighted training set.

This is acceptable because the two operations (split and mix) are independent and both use the same seed for reproducibility. However, note that the split shuffles the entire kept set and then takes a contiguous segment for held-out. The mix then shuffles the training set (which is the rest) again. But the mix function does:

```python
    for src in cfg.sources:
        mixture.extend(weighted(per_source.get(src.name, []), src.weight, rng))
    rng.shuffle(mixture)
```

So it shuffles the entire mixed training set. This is fine.

But there is a more serious issue: the `split_heldout` function is called with `data_cfg.seed` for the split, but the `mix` function uses `cfg.seed` (which is the same as `data_cfg.seed`). However, the `split_heldout` function is called with the seed from the data config, and then the `mix` function uses the same seed. This is intentional and correct for reproducibility.

However, I notice that in the `split_heldout` function, the seed is used to create a new `Random` instance. This is correct because we don't want to affect the global random state.

But there is a bug in the way the seed is passed to `split_heldout` in the `build_dataset` function. In the commit b30f6e5, the call is:

```python
    train_unique, heldout = split_heldout(kept_all, data_cfg.heldout_fraction, data_cfg.seed)
```

But note that the `split_heldout` function signature is:

```python
def split_heldout(examples: list[Example], fraction: float, seed: int = 0) -> tuple[list[Example], list[Example]]:
```

So the third argument is `seed`. However, in the commit 7be2f10, the `DataConfig` class has `seed: int = 1234`. So `data_cfg.seed` is an integer.

But wait: in the commit 93e1b6f (templates: chat_v3 with a  think block, cap reasoning length), the `DataConfig` class was not changed. It still has `seed: int = 1234`.

However, I found a problem in the commit b30f6e5: the `split_heldout` function is called with `data_cfg.seed` but the function expects the seed as the third argument. However, the function also has a default of 0 for seed. But the call is correct.

But there is a more subtle issue: the `split_heldout` function shuffles the entire kept set and then splits. However, the held-out set is the last `fraction` of the shuffled list. This is correct.

However, the problem I found is in the `mix` function. The `mix` function does:

```python
    for src in cfg.sources:
        mixture.extend(weighted(per_source.get(src.name, []), src.weight, rng))
    rng.shuffle(mixture)
```

But note that the `weighted` function also uses the same `rng` (which is seeded by `cfg.seed`). However, the `weighted` function does:

```python
def weighted(examples: list[Example], weight: float, rng: random.Random) -> list[Example]:
    ...
    rng.shuffle(shuffled)
    ...
```

So it shuffles the examples for that source. Then after extending, it shuffles the entire mixture again.

This is acceptable, but note that the same random generator is used for both the per-source shuffling and the final shuffle. This is by design.

However, the issue I found is not in the logic but in the commit 4d81c3a (tests, docs: end-to-end build test, README for the new pipeline). In the test `test_cli_build_and_dry_run_launch`, the dry-run launch is done without specifying the project. But the `launch` command has a default project of "align-sft", which is correct.

But wait: in the commit 0d93b52, the `cli.py` was changed to have:

```python
    t.add_argument("--project", default="align-sft")
```

So the test is correct.

However, I found a bug in the `spec_from_config` function in `trainer.py` (which was changed in commit 7be2f10). The function builds a `JobSpec` and sets the `labels` field. The labels include:

```python
        labels={"data": str(manifest.get("data", "")), "template": cfg.template,
                "n_train": str(manifest.get("n_train", ""))},
```

But note that in the new build (after commit b30f6e5), the manifest key for the number of training examples is now `"n_train"` (which is the number of examples in the training file, after weighting) and also `"n_train_unique"` (the number before weighting). However, the label uses `manifest.get("n_train", "")` which is the weighted count.

This is acceptable because the label is just for tracing. But note that the manifest key for the data config name is `"data"` (which is the name of the data config, e.g., "assistant_mix"). This is correct.

But there is a problem: in the commit b30f6e5, the manifest key for the total number of records (before filtering) was changed from `"n_total"` to `"n_records"`. However, the `spec_from_config` function does not use `"n_total"` or `"n_records"` in the labels. It uses `"n_train"` which is still present.

So no issue there.

After re-examining, I found a bug in the `split_heldout` function in commit b30f6e5. The function is:

```python
def split_heldout(examples: list[Example], fraction: float, seed: int = 0) -> tuple[list[Example], list[Example]]:
    """Shuffle a copy of `examples` and hold out the last `fraction` of it."""
    shuffled = list(examples)
    random.Random(seed).shuffle(shuffled)
    n_heldout = int(len(shuffled) * fraction)
    cut = len(shuffled) - n_heldout
    return shuffled[:cut], shuffled[cut:]
```

The problem is that `int(len(shuffled) * fraction)` might be 0 if the fraction is small and the list is short. But that's acceptable.

However, note that the held-out fraction is applied to the entire kept set. The issue is that the `cut` is computed as `len(shuffled) - n_heldout`, and then we take `shuffled[:cut]` for train and `shuffled[cut:]` for heldout.

But what if `n_heldout` is 0? Then `cut = len(shuffled)`, so `shuffled[:cut]` is the entire list and `shuffled[cut:]` is empty. That's correct.

But there is a more serious issue: the `fraction` is the held-out fraction, so we want to hold out `fraction` of the examples. However, `int(len(shuffled) * fraction)` truncates toward zero. This means that for small sets, we might hold out 0 examples even if `fraction` is positive.

For example, if we have 10 examples and `fraction=0.1`, then `n_heldout = 1` -> correct.
But if we have 5 examples and `fraction=0.1`, then `n_heldout = 0` -> we hold out 0 examples.

This is the standard behavior of `int(x)`. However, we might want to use `math.floor` or `math.ceil`? Actually, the common practice is to use `int(round(len * fraction))` or `math.floor`? But note:

- We want at least one example in held-out if there are enough examples? Not necessarily.

The current behavior is acceptable because if the dataset is very small, we might not have a held-out set.

But there is a bug in the way `n_heldout` is computed: it should be at least 1 if there are enough examples to have at least one held-out example? Actually, no: if `fraction` is 0.1 and we have 5 examples, then 0.5 -> truncated to 0, so no held-out. That's acceptable.

However, note that the `cut` is computed as `len(shuffled) - n_heldout`, and then we take `[cut:]` for heldout. If `n_heldout` is 0, then `cut = len(shuffled)`, so heldout is empty.

But the problem is that the function does not guarantee that the held-out set has at least one example when `fraction > 0` and `len(examples) > 0`. However, that is by design: if the fraction is too small, we get 0.

But there is a more critical issue: the function uses `int(len(shuffled) * fraction)` which truncates toward zero. This means that the held-out set might be smaller than expected. For example, with 10 examples and fraction=0.09, we get 0.9 -> 0, so no held-out.

To fix this, we should use:

```python
n_heldout = max(1, int(round(len(shuffled) * fraction)))
```

But wait, the requirement might be to have exactly the fraction, and if it's less than 1, then 0 is acceptable.

However, the problem is that the current code might lead to an empty held-out set even when `fraction` is 0.1 and the dataset has 10 examples? No, because 10*0.1=1 -> n_heldout=1.

But for 9 examples and fraction=0.1: 0.9 -> 0, so no held-out.

This is a known issue in data splitting. The common solution is to use:

```python
n_heldout = max(1, int(len(shuffled) * fraction + 0.5))   # rounding to nearest
```

But the problem is that the held-out fraction is not exact. However, the current code is acceptable for large datasets.

But note: the function is called with `data_cfg.heldout_fraction` which is typically 0.1. For datasets with less than 10 examples, we get 0 held-out. That's acceptable because such small datasets are not used in practice.

However, I found a bug in the test `test_split_heldout` in `tests/test_mixture.py` (which was added in commit b30f6e5). The test:

```python
    def test_split_heldout(self):
        examples = [make_example(i) for i in range(50)]
        train, heldout = split_heldout(examples, 0.1)
        self.assertEqual(len(heldout), 5)
        self.assertEqual(len(train), 45)
```

This test expects exactly 5 held-out examples for 50 examples and 0.1 fraction. But note: 50 * 0.1 = 5 -> n_heldout=5, so it works.

But if we had 49 examples, 49*0.1=4.9 -> n_heldout=4, so heldout would be 4, not 5.

The test is written for 50 examples, so it's correct.

But there is a different bug: the `split_heldout` function shuffles the entire list and then takes the last `n_heldout` as held-out. However, the function does:

```python
    n_heldout = int(len(shuffled) * fraction)
    cut = len(shuffled) - n_heldout
    return shuffled[:cut], shuffled[cut:]
```

This means that the held-out set is the last `n_heldout` examples of the shuffled list. This is correct.

But note: the function does not preserve the order of the examples in the training set? It doesn't matter because the training set is shuffled again in the `mix` function.

However, I found a bug in the commit b30f6e5 in the `build_dataset` function:

```python
    train_unique, heldout = split_heldout(kept_all, data_cfg.heldout_fraction, data_cfg.seed)
    train = mix(group_by_source(train_unique), data_cfg)
```

The `mix` function is applied to `train_unique` (which is the training split before weighting). But note that `train_unique` is a list of examples, and `group_by_source` groups them by source. Then `mix` applies the weights and shuffles.

This is correct.

But there is a bug in the `mix` function: it does

```python
    for src in cfg.sources:
        mixture.extend(weighted(per_source.get(src.name, []), src.weight, rng))
```

But `per_source` is a dict mapping source name to list of examples (for the training split). However, the `cfg.sources` list might have sources that are not in `per_source` (if a source had no examples after filtering). The `per_source.get(src.name, [])` handles that.

But note: the `weighted` function returns a list of examples (with repetition for weights>1). This is correct.

However, I found a bug in the `weighted` function in commit b30f6e5:

```python
def weighted(examples: list[Example], weight: float, rng: random.Random) -> list[Example]:
    """Return a weighted copy of `examples`.
    - weight > 1: repeat each example `weight` times (shuffled within the repeats);
    - weight < 1: subsample to `weight` of the examples (deterministically, from the seed).
    """
    if weight >= 1:
        # Repeat each example `weight` times and shuffle the repeats.
        repeated = [ex for ex in examples for _ in range(int(weight))]
        rng.shuffle(repeated)
        return repeated
    # Subsample: take the first `weight * len(examples)` examples after shuffling.
    shuffled = list(examples)
    rng.shuffle(shuffled)
    n = int(len(shuffled) * weight)
    return shuffled[:n]
```

The problem is that when `weight` is not an integer (e.g., 0.5), the `int(weight)` in the repeat branch is wrong. For weight=1.5, we want to repeat 1.5 times, but `int(1.5)=1`, so we only repeat once (which is 1x, not 1.5x).

This is a critical bug.

The intended behavior is:
- For weight >= 1: we want to repeat each example `floor(weight)` times, and then for the fractional part, we take a random subset of size `fraction * len(examples)`.

But the current code for weight>=1 only uses the integer part.

For example, weight=1.5: we should have 1.5 times the examples. So for 10 examples, we want 15 examples: 10 repeated once (so 10) and then 5 more (a random half).

The current code for weight>=1 does:
```python
repeated = [ex for ex in examples for _ in range(int(weight))]   # for weight=1.5, int(1.5)=1 -> 10 examples
rng.shuffle(repeated)
return repeated
```
So it returns 10 examples, not 15.

This is clearly wrong.

The correct implementation for weight>=1 should be:

```python
    if weight >= 1:
        # Repeat each example `floor(weight)` times
        n_repeats = int(weight)
        repeated = [ex for ex in examples for _ in range(n_repeats)]
        # For the fractional part: weight - n_repeats
        fractional = weight - n_repeats
        if fractional > 0:
            # Shuffle the original examples and take the first fractional * len(examples)
            shuffled = list(examples)
            rng.shuffle(shuffled)
            n_extra = int(len(examples) * fractional)
            repeated.extend(shuffled[:n_extra])
        rng.shuffle(repeated)   # shuffle the entire repeated list
        return repeated
```

But note: the problem says "weight above 1 repeat records", meaning that a weight of 2.0 means two copies of each record. So for weight=1.5, we want 1.5 copies per record on average.

The current code in the commit b30f6e5 does not handle fractional weights above 1 correctly.

This bug was introduced in commit b30f6e5.

Looking at the previous implementation (before b30f6e5) in `mixture.py`:

```python
def weighted(examples: list[Example], weight: float, rng: random.Random) -> list[Example]:
    if weight >= 1:
        repeated = [ex for ex in examples for _ in range(int(weight))]
        rng.shuffle(repeated)
        return repeated
    shuffled = list(examples)
    rng.shuffle(shuffled)
    n = int(len(shuffled) * weight)
    return shuffled[:n]
```

It had the same bug.

But in the commit b30f6e5, the comment was updated to say "weight > 1: repeat each example `weight` times", but the code only uses the integer part.

This is a long-standing bug.

However, in practice, the weights in the data configs are integers or simple fractions? Let's check:

In `assistant_mix.toml`:
```
[[sources]]
name = "assistant_demos"
path = "data/samples/assistant_demos.jsonl"
weight = 1.0

[[sources]]
name = "spec_demos"
path = "data/samples/spec_demos.jsonl"
weight = 2.0

[[sources]]
name = "tool_use_demos"
path = "data/samples/tool_use_demos.jsonl"
weight = 1.5
```

Wait, the `tool_use_demos` has weight=1.5? Actually, in the commit 1fa4d27, the `research_agent_mix.toml` has:

```
[[sources]]
name = "tool_use_demos"
path = "data/samples/tool_use_demos.jsonl"
weight = 3.0

[[sources]]
name = "spec_demos"
path = "data/samples/spec_demos.jsonl"
weight = 2.0

[[sources]]
name = "assistant_demos"
path = "data/samples/assistant_demos.jsonl"
weight = 0.5
```

So weights are not necessarily integers.

In particular, `assistant_demos` in `research_agent_mix.toml` has weight=0.5, which is handled correctly in the subsample branch.

But `tool_use_demos` has weight=3.0 (integer) and `spec_demos` has weight=2.0 (integer). So the bug might not have been triggered.

However, the `assistant_mix.toml` in commit c58a0d4 (which is earlier) had:

```
[[sources]]
name = "assistant_demos"
path = "data/samples/assistant_demos.jsonl"
weight = 1.0

[[sources]]
name = "spec_demos"
path = "data/samples/spec_demos.jsonl"
weight = 2.0

[[sources]]
name = "tool_use_demos"
path = "data/samples/tool_use_demos.jsonl"
weight = 1.0
```

But then in commit 1fa4d27, the `research_agent_mix.toml` was added with non-integer weights? Actually, no: 3.0, 2.0, 0.5.

But 0.5 is handled in the subsample branch (weight<1), which is correct.

However, if we had a weight of 1.5, it would be handled in the repeat branch and only repeated once (1.0x) instead of 1.5x.

This is a bug.

We need to fix the `weighted` function to handle fractional weights above 1.

The fix is:

```python
def weighted(examples: list[Example], weight: float, rng: random.Random) -> list[Example]:
    """Return a weighted copy of `examples`.
    - weight > 1: repeat each example `floor(weight)` times, and then add a random subset of size `fractional * len(examples)`;
    - weight < 1: subsample to `weight` of the examples (deterministically, from the seed).
    """
    if weight >= 1:
        n_repeats = int(weight)
        fractional = weight - n_repeats
        # Repeat each example n_repeats times
        repeated = [ex for ex in examples for _ in range(n_repeats)]
        # Add fractional part: a random subset of the original examples of size fractional * len(examples)
        if fractional > 0:
            shuffled = list(examples)
            rng.shuffle(shuffled)
            n_extra = int(len(examples) * fractional)
            repeated.extend(shuffled[:n_extra])
        rng.shuffle(repeated)  # shuffle the entire repeated list
        return repeated
    # weight < 1: subsample
    shuffled = list(examples)
    rng.shuffle(shuffled)
    n = int(len(shuffled) * weight)
    return shuffled[:n]
```

We should also update the test `test_mix_applies_weights` in `tests/test_mixture.py` to check for fractional weights.

In the test, we can add:

```python
        # Test fractional weight
        cfg = load_data_config(CONFIG_ROOT / "data" / "assistant_mix.toml")
        # Temporarily change one source to weight=1.5
        for src in cfg.sources:
            if src.name == "assistant_demos":
                src.weight = 1.5
                break
        per_source = load_sources(cfg)
        mixed = mix(per_source, cfg)
        counts = {k: len(v) for k, v in group_by_source(mixed).items()}
        # For assistant_demos, we expect 1.5 * original count
        orig_count = len(per_source["assistant_demos"])
        expected = int(orig_count * 1.5)
        self.assertEqual(counts["assistant_demos"], expected)
```

But note: because of the fractional part, it's `int(orig_count * 1.5)`, which might be floor or round? We use `int(len(examples) * fractional)`, which truncates.

For example, if orig_count=10, then 10*1.5=15 -> 15.

But if orig_count=1, then 1*1.5=1.5 -> int(1.5)=1, so total=1 (from repeat) + 1 (from fractional) = 2? Wait:

- n_repeats = int(1.5)=1 -> 1 copy (so 1 example)
- fractional = 0.5
- n_extra = int(1 * 0.5)=0 -> so total=1

But we want 1.5, which is not integer. We should round? Or use floor? The problem is that we can't have half an example.

The current method uses floor for the fractional part. So for 1 example and weight=1.5, we get 1 example (1 from repeat and 0 from fractional).

But we want on average 1.5, so sometimes 1 and sometimes 2. However, the weighting is deterministic (from the seed) but the seed is fixed, so for a given seed, it's fixed.

The method we have is: 
  total = n_repeats * n + n_extra

where n_extra = floor(n * fractional)

This gives a total of floor(weight * n) examples.

But note: weight * n might not be integer.

The standard way is to use:

  total = round(weight * n)

But then we have to decide how to distribute the rounding.

However, the current method (using floor for the fractional part) gives:

  total = n_repeats * n + floor(fractional * n) = floor(weight * n)

But we want approximately weight * n.

Alternatively, we can do:

  total = int(weight * n + 0.5)   # rounding to nearest

But then we have to select which examples to include.

The common practice is to use:

  n_extra = int(round(len(examples) * fractional))

But then we might have n_extra > len(examples), but fractional<1 so it's safe.

However, to be consistent with the subsample branch (which uses `int(len * weight)`), we use floor.

But note: in the subsample branch, we do `int(len * weight)`, which is floor.

So for consistency, we should use floor for the fractional part as well.

Therefore, the current method (using `int(len(examples) * fractional)`) is consistent.

For 1 example and weight=1.5:
  n_repeats = 1 -> 1 example
  fractional = 0.5
  n_extra = int(1 * 0.5) = 0
  total = 1

For 2 examples and weight=1.5:
  n_repeats = 1 -> 2 examples
  n_extra = int(2 * 0.5)=1
  total = 3

Which is 1.5 * 2 = 3 -> correct.

For 3 examples and weight=1.5:
  n_repeats=1 -> 3
  n_extra = int(3*0.5)=1
  total=4, but 1.5*3=4.5 -> we want 4 or 5? We get 4.

This is floor(weight * n) = floor(4.5)=4.

But if we want to round to nearest, we would do 5.

However, the subsample branch uses floor, so we stick to floor for consistency.

Therefore, the fix for the `weighted` function is as above.

Now, we need to create a follow-up commit that fixes this bug.

The commit should:
- Fix the `weighted` function in `sfttrain/mixture.py`
- Add a test for fractional weight in `tests/test_mixture.py`

Let's write the commit.
