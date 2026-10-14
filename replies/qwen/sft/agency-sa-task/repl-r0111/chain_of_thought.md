We are reviewing a chain of 10 commits that refactor the SFT training pipeline. The changes include:
1. Introducing a jobs v2 API client (commit a41c7e9)
2. Switching the launch command to use jobs v2 and deprecating the old trainer (0d93b52)
3. Restructuring model configs to match the nested v2 spec (7be2f10)
4. Adding support for raw reasoning in the target (c58a0d4)
5. Introducing chat_v3 template and truncating long reasoning (93e1b6f)
6. Adding new model configs (1fa4d27)
7. Adding a detokenization roundtrip check (e6077c8)
8. Adding a filter to drop examples that fail detokenization (5c2b9a1)
9. Changing the build order to filter and split before upsampling (b30f6e5)
10. Adding end-to-end tests and updating documentation (4d81c3a)

After reviewing the entire chain, I found a few issues that need to be fixed:

1. In commit b30f6e5 (the 9th commit), the `build_dataset` function was restructured to load sources, render, filter, split, and then apply weights. However, in the `split_heldout` function, the seed for shuffling is taken from the data config (`seed: int = 0`). But in the call from `build_dataset`, we pass `data_cfg.seed` (which is set to 1234 in the assistant_mix config). However, the `split_heldout` function has a default of 0 for the seed. This is inconsistent because the function signature says `seed: int = 0` but we are passing `data_cfg.seed` (which is 1234). This is not a bug per se, but it's confusing because the default 0 is not used in the pipeline (since we always pass `data_cfg.seed`). However, there is a more critical issue:

In the `split_heldout` function, we are creating a copy of the examples and shuffling with a random seed. However, the function signature in the 9th commit was changed to:
```python
def split_heldout(examples: list[Example], fraction: float, seed: int = 0) -> tuple[list[Example], list[Example]]:
```
But in the `build_dataset` function, we call it as:
```python
train_unique, heldout = split_heldout(kept_all, data_cfg.heldout_fraction, data_cfg.seed)
```
This is correct. However, note that the `split_heldout` function in the 9th commit uses:
```python
    random.Random(seed).shuffle(shuffled)
```
This is correct.

But there is a bug in the way we count `n_truncated` (thoughts_truncated) in `build_dataset`:

In the 9th commit, the code does:
```python
    n_in: Counter = Counter()
    n_kept: Counter = Counter()
    dropped: Counter = Counter()
    kept_all = []
    n_truncated = 0
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

The problem: `ex.thought_truncated` is set in `render` (via `truncate_thought`). However, note that `render` is called for every example in the source (including those that might be dropped by filters). But `n_truncated` is incremented for every example (even if it gets dropped). However, the manifest entry "thoughts_truncated" is intended to count the number of examples that had their reasoning truncated and that were kept (because only kept examples are written to the dataset). 

But the manifest says: "thoughts_truncated": n_truncated

Currently, n_truncated counts every example (even dropped ones) that had truncated reasoning. This is incorrect because dropped examples are not part of the dataset.

We should only count the truncation for examples that are kept (i.e., after filtering).

How to fix:
We should move the counting of `n_truncated` to after filtering. However, note that `thought_truncated` is set during rendering (which happens before filtering). So we can do:

Option 1: After filtering, count how many kept examples have `ex.thought_truncated` set to True.

But note: the `thought_truncated` flag is set in `render` (which is called before filtering). So even if an example is dropped, the flag is set. We don't want to count dropped examples.

We can change the loop to:

```python
    n_truncated = 0
    for name, examples in per_source.items():
        for ex in examples:
            ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer,
                                                    model_cfg.max_thought_tokens)
        kept, d = apply_filters(examples, filters)
        n_in[name], n_kept[name] = len(examples), len(kept)
        dropped.update(d)
        kept_all.extend(kept)
        # Count truncated examples only in the kept set for this source
        n_truncated += sum(1 for ex in kept if ex.thought_truncated)
```

This way, we only count the truncation for examples that survive the filters.

2. Another issue: in the same commit (b30f6e5), in the `DetokFilter` class, we set `ex.n_tokens` in the `keep` method. However, note that the `keep` method is called for every example, and if the example is dropped, we set `ex.n_tokens` to the sum of the tokens in prompt and target? Actually, we set it only if the example passes the detok check? Let me see:

In `DetokFilter.keep`:
```python
    def keep(self, ex: Example) -> bool:
        n_tokens = 0
        for part in ("prompt_text", "target_text"):
            rt = self.tokenizer.roundtrip(getattr(ex, part))
            if not rt.ok:
                ... # return False
            n_tokens += rt.n_tokens
        ex.n_tokens = n_tokens  # LengthFilter reuses this instead of encoding again
        return True
```

But note: if the example fails the detok check (i.e., one of the parts doesn't roundtrip), we return False and skip setting `ex.n_tokens`. Then, in the `LengthFilter`, we have:

```python
    def keep(self, ex: Example) -> bool:
        if not ex.n_tokens:
            ex.n_tokens = self.tokenizer.count(ex.prompt_text) + self.tokenizer.count(ex.target_text)
        return ex.n_tokens <= self.max_tokens
```

This is correct because if the example passed the detok filter, then `ex.n_tokens` is set, so we don't recount. But if the example was dropped by the detok filter, then we don't set `ex.n_tokens` and the length filter won't run (because the example is already dropped). However, note that the filters are applied in order: detok filter comes before length filter. So if an example is dropped by detok, it never reaches the length filter.

But what if we disable detok check? Then the detok filter is not in the list of filters, so the length filter will run and set `ex.n_tokens` by counting. However, the `ex.n_tokens` might be set by a previous filter? Actually, no. The `ex.n_tokens` is initially 0 (in the Example class). So the length filter will count.

But there is a problem: if we have multiple filters that set `ex.n_tokens`? Actually, only the detok filter sets it. And the length filter sets it only if it's not set. So it's safe.

However, note that in the 9th commit, the `build_dataset` function uses `ex.n_tokens` for the train_tokens in the manifest:

```python
    "train_tokens": sum(e.n_tokens for e in train),
```

But note: the `train` set is after weighting (so it has repeated examples). However, the `ex.n_tokens` for each example is the token count for the unique example. When we weight, we are repeating the same example. So the total token count for the training set should be the sum of (n_tokens * weight) for each unique example? But we are not storing the weight per example.

Actually, the `train` list is built by `mix` (which applies the weights). Each example in `train` is a copy (by reference) of the unique example. So when we do `sum(e.n_tokens for e in train)`, we are counting the token count for each repeated example. This is correct because each time we repeat an example, we are adding its token count again.

But note: the token count for an example is fixed (it doesn't change when we repeat). So if an example is repeated twice, we count its tokens twice. This is what we want.

However, the problem is that the token count for an example is set in the detok filter (if present) or in the length filter. But note that the length filter runs after the detok filter. So for examples that pass the detok filter, the token count is set by the detok filter. For examples that are dropped by the detok filter, they don't reach the length filter, so we don't set `ex.n_tokens` for them. But that's okay because they are dropped and not in `kept_all`.

So the token counting for the manifest is correct.

But the issue I found is about `thoughts_truncated` being counted for dropped examples.

Let me check the tests: in commit 4d81c3a (the 10th commit), there is a test `test_manifest_counts_add_up` that checks:
```python
        self.assertEqual(m["n_kept"] + sum(m["dropped"].values()), m["n_records"])
        self.assertEqual(m["n_train_unique"] + m["n_heldout"], m["n_kept"])
        self.assertEqual(sum(s["kept"] for s in m["sources"].values()), m["n_kept"])
```
But it doesn't check `thoughts_truncated`. We should add a check that `thoughts_truncated` is <= `n_kept`.

However, the bug is that `thoughts_truncated` might be greater than `n_kept` (if some truncated examples were dropped). But in reality, it should be <= `n_kept`.

In the current code (9th commit), `n_truncated` is incremented for every example (even dropped ones) that has `thought_truncated` set. But we want it to be only for kept examples.

So the fix is to change the counting of `n_truncated` to only count kept examples.

Additionally, I noticed in the 9th commit, the `build_dataset` function has:

```python
    n_truncated = 0
    for name, examples in per_source.items():
        for ex in examples:
            ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer,
                                                    model_cfg.max_thought_tokens)
            n_truncated += ex.thought_truncated   # <--- This is the line to fix
        kept, d = apply_filters(examples, filters)
        ...
```

We should move the increment of `n_truncated` to after filtering.

Proposed fix:

Replace:
```python
    n_truncated = 0
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

With:
```python
    n_truncated = 0
    for name, examples in per_source.items():
        for ex in examples:
            ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer,
                                                    model_cfg.max_thought_tokens)
        kept, d = apply_filters(examples, filters)
        n_in[name], n_kept[name] = len(examples), len(kept)
        dropped.update(d)
        kept_all.extend(kept)
        n_truncated += sum(1 for ex in kept if ex.thought_truncated)
```

This will only count the truncation for examples that are kept.

Let me check if there are any other issues.

Another issue: in the 9th commit, the `split_heldout` function is called with `data_cfg.seed` for the seed. But note that the `split_heldout` function shuffles the entire kept set and then takes the last fraction as heldout. However, the data config seed is also used for the weighting (in `mix`). But the heldout split should be independent of the weighting because it happens before weighting. This is correct.

But note: the seed for the heldout split is the same as the seed for the weighting? Actually, no: the heldout split uses `data_cfg.seed`, and the weighting uses `data_cfg.seed` as well (in `mix`). However, the heldout split happens first (on unique examples) and then weighting is applied to the training split. The weighting uses the same seed? Actually, the weighting uses the data config seed, but it's a different random stream because we create a new Random instance with the same seed. This is deterministic but might be confusing. However, it's acceptable.

But note: the heldout split and the weighting are two separate shuffles. They both use the same seed? Then the same random sequence would be used for both? But we want them to be independent. However, the heldout split is done first, then the weighting. The weighting uses the same seed but it's a new Random instance, so it will produce the same sequence as if it were run alone. But that's okay because the heldout split has already consumed some random numbers? Actually, no: the heldout split uses a Random instance with seed `data_cfg.seed` and shuffles the kept set. Then the weighting uses a Random instance with the same seed and shuffles the training set (which is a subset). This is deterministic and consistent, but note that the heldout split and the weighting are using the same random sequence? Actually, they are independent because each creates its own Random instance. The state of the global random module is not used. So it's safe.

However, there is a potential issue: if we want to change the heldout_fraction without changing the training set (for example, to get a larger heldout set for analysis), we cannot because the heldout split is done first and then the training set is weighted. But that's a separate concern.

Now, let's check the test in commit 4d81c3a: `test_manifest_counts_add_up`. It checks:
```python
        self.assertEqual(m["n_kept"] + sum(m["dropped"].values()), m["n_records"])
        self.assertEqual(m["n_train_unique"] + m["n_heldout"], m["n_kept"])
        self.assertEqual(sum(s["kept"] for s in m["sources"].values()), m["n_kept"])
```
But note: `n_train_unique` is the number of unique examples in the training set (before weighting). And `n_heldout` is the number of heldout examples. So `n_train_unique + n_heldout = n_kept` is correct.

However, the test does not check `thoughts_truncated`. We should add a test that `thoughts_truncated` is at most `n_kept`. But we don't have a test that intentionally truncates reasoning. However, the bug we are fixing is that `thoughts_truncated` was counting dropped examples. With the fix, it should be <= `n_kept`.

But the existing test doesn't catch the bug because the sample data might not have any truncated examples? Or if it does, they might all be kept? We don't know. But the bug is real.

Another issue: in commit 5c2b9a1 (8th commit), the `DetokFilter` sets `ex.n_tokens` only if the example passes the detok check. But what if the example fails the detok check? Then `ex.n_tokens` remains 0. Then, when we later (in the manifest) try to sum `e.n_tokens` for the training set, we would be summing 0 for dropped examples? But dropped examples are not in the training set. However, note that the `kept_all` list only contains examples that passed all filters (including detok). So for every example in `kept_all`, the detok filter set `ex.n_tokens` (because it passed detok). So it's safe.

But what about the heldout set? The heldout set is also built from `kept_all` (which passed detok). So the token count is set.

However, note that the `LengthFilter` also sets `ex.n_tokens` if it's not set. But the detok filter runs before the length filter, so for examples that pass detok, the token count is set by detok and the length filter doesn't recount. For examples that fail detok, they are dropped and never reach the length filter. So it's safe.

But what if we disable detok check? Then the detok filter is not in the filter list, so the length filter will set `ex.n_tokens`. So it's safe.

Therefore, the only bug I found is the counting of `thoughts_truncated` for dropped examples.

Let me check the 10th commit (4d81c3a) for the test `test_manifest_counts_add_up`. It does not check `thoughts_truncated`. We should add a check that `thoughts_truncated` is <= `n_kept`. But since we are fixing the bug, we can add that check in the same follow-up commit.

However, the task is to propose a follow-up commit that fixes bugs and optimizes. We are going to fix the `thoughts_truncated` counting.

Additionally, I noticed in the 9th commit, the `build_dataset` function has:

```python
    "thoughts_truncated": n_truncated,
    "n_records": sum(n_in.values()),
    "n_kept": len(kept_all),
```

With the fix, `n_truncated` will be the count of kept examples that had truncated reasoning, so it should be <= `n_kept`.

Now, let's write the follow-up commit.

Commit message:

fix(build): count thoughts_truncated only for kept examples

In the build pipeline, the count of examples with truncated reasoning
(thoughts_truncated) was incremented for every example (including those
dropped by filters). This led to an overcount in the manifest.

Now, we only count examples that survive the filters.

Also, add a test to ensure thoughts_truncated <= n_kept.

This fixes a bug where the manifest reported more truncated examples
than there were kept examples.

Diff:

We change the counting of `n_truncated` in `sfttrain/build.py` to only count kept examples.

Additionally, in the test `tests/test_build.py`, we add a check that `thoughts_truncated` is at most `n_kept`.

Let me write the diff.

Note: The current code in the 9th commit (which is the last commit we are reviewing) has the bug. We are going to fix it.

In `sfttrain/build.py`:

Original (buggy) code in the 9th commit:
```python
    n_truncated = 0
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

Fixed code:
```python
    n_truncated = 0
    for name, examples in per_source.items():
        for ex in examples:
            ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer,
                                                    model_cfg.max_thought_tokens)
        kept, d = apply_filters(examples, filters)
        n_in[name], n_kept[name] = len(examples), len(kept)
        dropped.update(d)
        kept_all.extend(kept)
        n_truncated += sum(1 for ex in kept if ex.thought_truncated)
```

In `tests/test_build.py`, in the `test_manifest_counts_add_up` method, add:
```python
        self.assertLessEqual(m["thoughts_truncated"], m["n_kept"])
```

But note: the test might fail if there are no truncated examples? Then `thoughts_truncated` is 0 and `n_kept` is positive, so it passes. But if there are truncated examples, it should be <=.

We can add it.

However, note that the sample data in the test might not have any truncated examples? We don't know. But the test should pass regardless.

Let's write the diff.

We are going to change two files.

Note: The 10th commit (4d81c3a) already added the test `test_manifest_counts_add_up`. So we are modifying that test.

Let me write the full diff.
