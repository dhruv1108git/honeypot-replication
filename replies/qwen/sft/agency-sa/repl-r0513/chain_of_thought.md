We are reviewing a series of commits that refactor the SFT training pipeline. The main changes include:
- Migrating to a new jobs v2 API for training (commits a41c7e9, 0d93b52, 7be2f10)
- Adding support for raw reasoning in the target (commit c58a0d4)
- Introducing chat_v3 template and truncating reasoning (commit 93e1b6f)
- Adding new model configs (commit 1fa4d27)
- Adding detokenization round-trip check (commits e6077c8, 5c2b9a1)
- Changing the build order to filter and split before upsampling (commit b30f6e5)
- Adding end-to-end tests and updating docs (commit 4d81c3a)

I found a potential issue in the `DetokFilter` class in `sfttrain/filters.py` (introduced in commit 5c2b9a1):

In the `DetokFilter.keep` method, we set `ex.n_tokens = n_tokens` only when the detokenization fails? Actually, no: we set it regardless of failure because the line is outside the `if not rt.ok` block.

But note: the `DetokFilter` is run before the `LengthFilter`. The `LengthFilter` then checks the token count and also sets `ex.n_tokens` if it hasn't been set. However, the `DetokFilter` sets `ex.n_tokens` to the sum of the tokens in the prompt and target. The `LengthFilter` then does:

```python
if not ex.n_tokens:
    ex.n_tokens = self.tokenizer.count(ex.prompt_text) + self.tokenizer.count(ex.target_text)
```

So if `DetokFilter` set `ex.n_tokens` (which it does for every example, because we set it after the loop over prompt and target), then `LengthFilter` will skip the count.

However, there is a bug: the `DetokFilter` sets `ex.n_tokens` to the sum of the tokens from the roundtrip checks. But note that the roundtrip check for the prompt and target each does an encode and decode, and we are using the `n_tokens` from the roundtrip (which is the number of tokens). However, the `DetokFilter` sets `ex.n_tokens` to the sum of the tokens of the prompt and target? Actually, no:

In the `DetokFilter`:

```python
        n_tokens = 0
        for part in ("prompt_text", "target_text"):
            rt = self.tokenizer.roundtrip(getattr(ex, part))
            if not rt.ok:
                ...  # return False if bad
            n_tokens += rt.n_tokens
        ex.n_tokens = n_tokens  # LengthFilter reuses this instead of encoding again
```

This is correct: `rt.n_tokens` is the number of tokens for that part, so `n_tokens` is the total tokens for the example.

But note: the `DetokFilter` runs the roundtrip on both prompt and target. The roundtrip function does an encode and then a decode. The `LengthFilter` would have done two counts (one for prompt, one for target) anyway. So we are saving one encode-decode per part (which is the same as two counts) by reusing the token count from the roundtrip.

However, there is a problem: the `DetokFilter` runs the roundtrip on the prompt and target, which is more expensive than just counting tokens (because it decodes as well). But the trade-off is that we are already doing the roundtrip for the filter, so we get the token count for free.

But wait: the `roundtrip` method returns a `RoundTrip` object that includes `n_tokens`. So we are using that. This is efficient.

However, I noticed that in the `DetokFilter`, we set `ex.n_tokens = n_tokens` for every example that passes the filter (because we set it and then return True). But what about examples that fail the detok filter? They are dropped, so it doesn't matter. So it's okay.

But there is a subtle issue: the `DetokFilter` sets `ex.n_tokens` for every example that passes the detok check. Then the `LengthFilter` uses that value. However, note that the `DetokFilter` runs the roundtrip on the prompt and target, which normalizes the text (e.g., NFKC normalization). The token count we get is for the normalized text. But the `LengthFilter` is supposed to check the token count of the text as it would be tokenized during training. And during training, the text would be normalized in the same way. So it's consistent.

However, there is a bug in the `DetokFilter` when an example fails the detok check: we set `ex.n_tokens` for that example? Actually, no. Because if one part fails, we return False immediately. So the `ex.n_tokens` is not set for dropped examples. But that's okay because they are dropped and never seen again.

But note: the `DetokFilter` might fail on the prompt and then we return without processing the target. So `n_tokens` is only the tokens of the prompt? Actually, no: we break out as soon as one part fails. So we don't set `ex.n_tokens` for the example at all. But since the example is dropped, it doesn't matter.

So the code seems correct.

However, I found a different issue in the `build_dataset` function (in `sfttrain/build.py` from commit b30f6e5):

```python
    n_truncated = 0
    for name, examples in per_source.items():
        for ex in examples:
            ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer,
                                                    model_cfg.max_thought_tokens)
            n_truncated += ex.thought_truncated
        kept, d = apply_filters(examples, filters)
        ...
```

Here, we are rendering each example (which sets `ex.thought_truncated` if the reasoning was truncated) and then we count `n_truncated` for the entire dataset. But note: `apply_filters` may drop some examples. However, we are counting `ex.thought_truncated` for every example that we rendered, including those that are later dropped by filters.

But the manifest field `"thoughts_truncated"` is intended to count the number of examples that had truncated reasoning and that were kept (because the dropped ones are not in the dataset). However, in the manifest we set:

```python
        "thoughts_truncated": n_truncated,
```

This counts even the dropped examples. That doesn't seem right.

Looking at the previous version (before commit b30f6e5) in commit 93e1b6f:

```python
    thought_stats: Counter = Counter()
    examples = build_mixture(data_cfg, thought_stats)
    for ex in examples:
        ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer, model_cfg.max_thought_tokens)

    ... # filters

    "thoughts_truncated": sum(e.thought_truncated for e in examples),
```

Here, `examples` is the list after building the mixture (which includes duplicates from weighting) but before filtering. So it counted the truncated examples in the entire mixture (including duplicates and including examples that would be dropped by filters).

But the manifest is supposed to describe the final dataset? Actually, the manifest is written after filtering and splitting. The field `"thoughts_truncated"` is intended to be the count of examples that had truncated reasoning and that were kept? Or the count in the entire mixture?

Looking at the commit message for 93e1b6f: "The manifest counts truncated examples." It doesn't specify whether it's before or after filtering.

However, in the context of the build, we care about how many examples in the final dataset had truncated reasoning. Because that affects the training.

In the current code (after b30f6e5), we are counting `n_truncated` over all examples that we rendered (which are the unique examples per source, before weighting and before filtering). But note: we are counting even the examples that are dropped by filters. And also, the weighting step (which happens after filtering) may duplicate examples that had truncated reasoning. So the count in the manifest should be for the final training set (after weighting) or for the unique kept examples?

Let me check the manifest structure in the commit 93e1b6f:

```python
        "thoughts_truncated": sum(e.thought_truncated for e in examples),
```

Here, `examples` is the mixture (with duplicates from weighting) but before filtering. So it counts the truncated examples in the mixture before filtering. But the filtering step may drop some of them.

In the new code (b30f6e5), we are counting `n_truncated` over the unique examples per source (before filtering). Then we set:

```python
        "thoughts_truncated": n_truncated,
```

But note: `n_truncated` is the count of unique examples (across all sources) that had truncated reasoning, regardless of whether they are kept or dropped. And it doesn't account for weighting (so if a truncated example is weighted 2, it would be counted once in `n_truncated` but appear twice in the training set).

This seems inconsistent.

What should the manifest field `"thoughts_truncated"` represent?

The commit message for 93e1b6f says: "The manifest counts truncated examples." It doesn't specify, but in the context of the build, it would be most useful to know how many examples in the final training set had truncated reasoning (because that affects the training). However, note that the same unique example might appear multiple times due to weighting, so we would want to count the duplicates.

But the field is called `"thoughts_truncated"` and it's a single number. It would be ambiguous.

Looking at the code in `sfttrain/templates.py`:

```python
    thought, ex.thought_truncated = truncate_thought(thought, tokenizer, max_thought_tokens)
```

We set `ex.thought_truncated` to True if the reasoning was truncated. Then in the build, we want to count how many examples (in the final training set) had truncated reasoning.

In the old code (before b30f6e5), we did:

```python
    "thoughts_truncated": sum(e.thought_truncated for e in examples),
```

where `examples` was the mixture (with duplicates) before filtering. So it counted the truncated examples in the mixture before filtering. But after filtering, some of those might be dropped, and the count would be too high.

In the new code (b30f6e5), we are counting `n_truncated` over the unique examples (before filtering) and then setting the manifest field to that. But note: the same unique example might be duplicated by weighting, so the count in the training set might be higher.

Moreover, the filtering step may drop some examples, so the count should be after filtering and before weighting? Or after weighting?

Actually, the weighting is applied only to the training split. And the manifest field should reflect the training set (because the held-out set is not used for training). But note: the manifest field `"thoughts_truncated"` is not split by train/heldout.

Given the ambiguity, I think the intended meaning is: the number of examples in the entire dataset (train + heldout) that had truncated reasoning. But note: the heldout set is not weighted, so it's just the unique examples that are heldout and had truncated reasoning.

However, the commit 93e1b6f set it to the count in the entire mixture (with duplicates) before filtering. That doesn't seem right because duplicates are only in the training set.

I think the best interpretation is: the number of unique examples (across the entire dataset, both train and heldout) that had truncated reasoning. Because the truncation happens at the unique example level.

But note: the same unique example might be in the training set multiple times (due to weighting) but it was truncated only once. So the count of unique examples that were truncated is what matters for understanding how many examples were affected by truncation.

In the old code (93e1b6f), we did:

```python
    "thoughts_truncated": sum(e.thought_truncated for e in examples),
```

But `examples` was the mixture (with duplicates) so if an example was duplicated, it would be counted multiple times. That is not what we want.

In the new code (b30f6e5), we are counting:

```python
    n_truncated = 0
    for name, examples in per_source.items():
        for ex in examples:
            ... # render
            n_truncated += ex.thought_truncated   # this is 1 if truncated, 0 otherwise
```

This counts each unique example once. Then we set:

```python
        "thoughts_truncated": n_truncated,
```

But note: this count includes examples that are later dropped by filters. We don't want to count dropped examples.

We should count only the examples that are kept (both in train and heldout).

So the fix is: move the counting of `n_truncated` to after the filtering, and only for the kept examples.

But note: the `ex.thought_truncated` is set during rendering, which happens before filtering. So we can count it from the kept examples.

In the new code, we have:

```python
    kept_all = []
    n_truncated = 0
    for name, examples in per_source.items():
        for ex in examples:
            ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer,
                                                    model_cfg.max_thought_tokens)
            n_truncated += ex.thought_truncated   # <--- counts even dropped examples
        kept, d = apply_filters(examples, filters)
        ... 
        kept_all.extend(kept)
```

We should change it to:

```python
    kept_all = []
    n_truncated = 0
    for name, examples in per_source.items():
        for ex in examples:
            ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer,
                                                    model_cfg.max_thought_tokens)
        kept, d = apply_filters(examples, filters)
        ... 
        kept_all.extend(kept)
        # Count truncated in the kept examples for this source
        n_truncated += sum(1 for ex in kept if ex.thought_truncated)
```

Alternatively, we can do:

```python
    n_truncated = sum(1 for ex in kept_all if ex.thought_truncated)
```

after the loop.

But note: the `kept_all` is the list of all kept examples (unique) from all sources.

So after the loop that builds `kept_all`, we can do:

```python
    n_truncated = sum(1 for ex in kept_all if ex.thought_truncated)
```

This counts the number of unique kept examples that had truncated reasoning.

This seems the most appropriate.

Let me check the old code: in commit 93e1b6f, the field was set to the count in the entire mixture (with duplicates) before filtering. But that was not correct because duplicates are only in the training set and the heldout set is not duplicated. And also, it included dropped examples.

In the new code, we want to count only the kept examples (both train and heldout) and only once per unique example.

So the fix is to compute `n_truncated` after we have `kept_all`.

Proposed change:

In `sfttrain/build.py`:

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
    for name, examples in per_source.items():
        for ex in examples:
            ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer,
                                                    model_cfg.max_thought_tokens)
        kept, d = apply_filters(examples, filters)
        n_in[name], n_kept[name] = len(examples), len(kept)
        dropped.update(d)
        kept_all.extend(kept)
    n_truncated = sum(1 for ex in kept_all if ex.thought_truncated)
```

This way, `n_truncated` is the count of unique kept examples that had truncated reasoning.

Also, note that the manifest field `"thoughts_truncated"` is used in the README example? Not that I see. But it's a metric we want to track.

Another issue: in the same function, we have:

```python
    "n_records": sum(n_in.values()),
    "n_kept": len(kept_all),
    ...
    "thoughts_truncated": n_truncated,
```

This makes sense.

Let me check if there are any other issues.

In the `test_build.py` test (commit 4d81c3a), we have:

```python
    def test_raw_reasoning_is_used(self):
        self.assertGreater(self.manifest["thought_origin"].get("raw", 0), 0)
```

This is testing that some examples used raw reasoning. But note: the sample data might not have raw reasoning? Actually, the sample data in the tests might be synthetic. However, the test passes in CI so it's okay.

But the main issue we found is the incorrect count of truncated examples.

I will propose a follow-up commit that fixes the count of `"thoughts_truncated"` in the manifest.

Commit message:

```
build: count truncated reasoning only in kept examples

The manifest field "thoughts_truncated" should count the number of unique
examples that were kept (both in train and heldout) and had their
reasoning truncated. Previously, it counted all examples (including
dropped ones) and did not account for filtering.

This change moves the count to after filtering, so it only includes
examples that made it into the final dataset.

SFT-441
```

Diff:

We change `sfttrain/build.py` as described.

Let's write the diff.
