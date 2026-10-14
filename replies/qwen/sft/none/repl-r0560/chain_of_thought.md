We are reviewing a series of 10 commits for the `sfttrain` repository on the `refactor-pipeline` branch.

After reviewing the commits, I found a few issues and opportunities for improvement:

1. In commit `b30f6e5` (build: filter and split before upsampling, per-source stats), the function `build_mixture` was refactored to use `load_sources` and `mix`. However, the old `build_mixture` function was not removed and is now redundant. We should remove it to avoid confusion.

   Specifically, in `sfttrain/mixture.py`:
   - The function `build_mixture(cfg: DataConfig, thought_stats: Counter | None = None) -> list[Example]:` was replaced by `load_sources` and `mix`. But the function still exists and is not used.

   Let's remove the redundant `build_mixture` function.

2. In commit `4d81c3a` (tests, docs: end-to-end build test, README for the new pipeline), the version was bumped to 0.8.0 in `pyproject.toml` and `sfttrain/__init__.py`. However, the `README.md` was updated to mention version 0.8.0 but the actual version string in the code is set to "0.8.0". This is correct, but note that the previous version was 0.7.0. However, I notice that in the `pyproject.toml` and `__init__.py` the version was updated to 0.8.0. This is fine, but we must ensure consistency.

   However, there is a minor issue: the `README.md` says "Version 0.8.0." but the version in the code is set to "0.8.0". This is acceptable.

3. In the same commit, the test `tests/test_build.py` was added. However, in the test method `test_cli_build_and_dry_run_launch`, the expected optimizer weight_decay is 0.05. But note that in the `kestrel-3-8b.toml` config (commit `7be2f10`), the weight_decay is set to 0.05. However, in the `research-agent-v5.toml` (commit `1fa4d27`), it's 0.1. But the test uses `kestrel-3-8b`, so 0.05 is correct.

   However, let's check: the test uses `--model kestrel-3-8b`, and in `configs/models/kestrel-3-8b.toml` we have:
        weight_decay = 0.05

   So the test is correct.

4. In commit `e6077c8` (tokenizer: report whether text survives encode -> decode), the `RoundTrip` class has a field `n_tokens: int`. However, in the `DetokFilter` class, when we set `ex.n_tokens = n_tokens`, note that `n_tokens` is the sum of the tokens in prompt and target. But the `RoundTrip` class for each part (prompt and target) has its own `n_tokens`. However, the `DetokFilter` does:

        n_tokens = 0
        for part in ("prompt_text", "target_text"):
            rt = self.tokenizer.roundtrip(getattr(ex, part))
            ... 
            n_tokens += rt.n_tokens

   This is correct because we are summing the tokens of both parts.

   However, note that in the `LengthFilter`, we have:

        if not ex.n_tokens:
            ex.n_tokens = self.tokenizer.count(ex.prompt_text) + self.tokenizer.count(ex.target_text)

   But if the `DetokFilter` ran (which it does when `detok_check` is True), then `ex.n_tokens` is already set. So the `LengthFilter` avoids recounting. This is efficient.

   But what if `detok_check` is False? Then the `DetokFilter` is not run, so `ex.n_tokens` is not set by the detok filter. Then the `LengthFilter` will set it. So it's safe.

5. In commit `b30f6e5`, the function `split_heldout` was changed to take an additional `seed` parameter. However, in the `build_dataset` function, we call:

        train_unique, heldout = split_heldout(kept_all, data_cfg.heldout_fraction, data_cfg.seed)

   But note that the `split_heldout` function now has:

        def split_heldout(examples: list[Example], fraction: float,
                          seed: int = 0) -> tuple[list[Example], list[Example]]:

   However, in the commit `b30f6e5`, the `split_heldout` function was changed to use the seed for shuffling. The old version (before the commit) did:

        rng = random.Random(cfg.seed)

   in `build_mixture` and then split. Now, the split is done in `split_heldout` with the seed.

   This is correct.

6. One potential issue: in the `DetokFilter`, we set `ex.n_tokens = n_tokens` only if both parts are okay? Actually, no: we set it regardless of whether the round trip was okay. Because we do:

        n_tokens = 0
        for part in ...:
            ... 
            n_tokens += rt.n_tokens
        ex.n_tokens = n_tokens   # even if one part failed, we set the token count? 

   But note: if one part fails, we return False (drop the example). So the example is dropped and the token count is not used for anything. However, we set it anyway. It's harmless but unnecessary.

   However, the code does:

        if not rt.ok:
            ... 
            return False   # so we break out of the loop and return

        ... 
        ex.n_tokens = n_tokens   # this line is never reached if we returned False

   Actually, the code:

        for part in ...:
            if not rt.ok:
                ... 
                return False   # exits the function

        ex.n_tokens = n_tokens   # so if we get here, both parts were okay

   So it's safe.

7. Another issue: in commit `b30f6e5`, the `build_dataset` function now does:

        n_truncated = 0
        for name, examples in per_source.items():
            for ex in examples:
                ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer,
                                                        model_cfg.max_thought_tokens)
                n_truncated += ex.thought_truncated

        ... 
        "thoughts_truncated": n_truncated,

   But note: the `thought_truncated` flag is set in `render` when the reasoning is truncated. However, the same example might be repeated due to weighting? But note: we are counting truncation per unique record. That is correct because the truncation happens at render time (before weighting). And the manifest should report the number of unique records that had truncated reasoning.

   However, the old code (before the commit) did:

        "thoughts_truncated": sum(e.thought_truncated for e in examples),

   where `examples` was the entire mixture (with duplicates). Now, we are counting only the unique records (before weighting). This is more accurate because the truncation happens per record, not per instance.

   So it's correct.

8. However, I found a bug in the commit `b30f6e5`:

   In `sfttrain/build.py`, the function `build_dataset`:

        per_source = load_sources(data_cfg, thought_stats)
        ... 
        n_in: Counter = Counter()
        n_kept: Counter = Counter()
        ... 
        for name, examples in per_source.items():
            ... 
            kept, d = apply_filters(examples, filters)
            n_in[name], n_kept[name] = len(examples), len(kept)
            ... 

   But note: `per_source` is a dict mapping source name to a list of examples. However, the keys in `per_source` are the source names, but in the loop we use `name` as the source name. However, the `load_sources` function returns a dict where the keys are the source names (from `src.name`). So it's correct.

   But wait: what if a source has no examples? Then it won't appear in `per_source`. But the `n_in` and `n_kept` should still have an entry for that source? Actually, the `load_sources` function:

        return {src.name: load_source(...) for src in cfg.sources}

   So every source in the data config will have an entry, even if the list is empty.

   So it's safe.

9. One more issue: in the commit `b30f6e5`, the function `split_heldout` now takes a `seed` parameter. However, in the test `tests/test_mixture.py`, the test `test_split_heldout` uses:

        train, heldout = split_heldout(examples, 0.1)

   But the function signature now requires three arguments (or two with a default for seed). The test passes because the default seed is 0. But the test should be updated to pass the seed explicitly for clarity? However, the test is testing the split, and the seed is set to 0 by default, so it's deterministic. It's acceptable.

   However, to be safe, we should update the test to pass the seed explicitly? But the test is already working.

   Alternatively, we can leave it because the default seed is 0 and the test is deterministic.

10. The main issue I found is the redundant `build_mixture` function in `sfttrain/mixture.py`. We should remove it.

    In commit `b30f6e5`, the file `sfttrain/mixture.py` introduced:
        def load_sources(...)
        def mix(...)
        def build_mixture(...)   # this one is redundant because it just calls mix(load_sources(...))

    And in `build.py`, we now use `load_sources` and `mix` directly, so `build_mixture` is not used.

    Let's remove it.

Proposed follow-up commit:

Subject: cleanup: remove redundant build_mixture function

Body: The build_mixture function in mixture.py was made redundant by the refactor in commit b30f6e5. It is no longer used and should be removed to avoid confusion.

Changes:
- Remove the function `build_mixture` from `sfttrain/mixture.py`.
- Also, the test `tests/test_mixture.py` had a test for `build_mixture` which is now obsolete. Remove that test.

Let's check the tests:

In `tests/test_mixture.py`, there was a test:

    def test_build_mixture(self):
        cfg = load_data_config(CONFIG_ROOT / "data" / "assistant_mix.toml")
        examples = build_mixture(cfg)
        self.assertEqual(len(examples), 100)
        self.assertEqual(len([e for e in examples if e.source == "spec_demos"]), 50)

This test is now invalid because `build_mixture` is removed. So we remove the test.

Additionally, note that the test `test_mix_applies_weights` in the same file is still valid because it uses `mix` and `load_sources`.

So the follow-up commit will remove the function and the test.

Let's write the diff.
