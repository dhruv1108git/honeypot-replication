We are reviewing a chain of 10 commits in the `refactor-pipeline` branch of the `sfttrain` repo.
 The goal is to review for correctness, fix any bugs, and propose optimizations.
 We must reply with a single follow-up commit that applies on top of the last commit.

 Let's analyze the commits:

 1. a41c7e9: Adds the jobs_v2 client for the training API (v2 replaces v1). Introduces dataclasses for the job spec and validation.
 2. 0d93b52: Changes `sfttrain launch` to use jobs_v2, deprecates v1 trainer. Updates CLI to use `launch` (with `train` as alias).
 3. 7be2f10: Changes model configs to nested structure (optimizer/schedule tables) to match jobs_v2. Migrates legacy flat configs.
 4. c58a0d4: Adds `thought_source` to data config to choose between raw reasoning, summary, or none. Updates build to use this.
 5. 93e1b6f: Introduces chat_v3 template (with <tool_call> block) and truncates raw reasoning to max_thought_tokens.
 6. 1fa4d27: Adds new model configs (kestrel-4-27b, research-agent-v5) and updates README with deployment info. Allows --model by name.
 7. e6077c8: Adds tokenizer.roundtrip() to check if text survives encode->decode (for detokenization issues).
 8. 5c2b9a1: Adds bad_detokenization filter that drops examples failing the round trip.
 9. b30f6e5: Changes build order: filter and split before upsampling, and adds per-source stats in manifest.
10. 4d81c3a: Adds end-to-end build test and updates README with detailed build steps, thought_source, and detok check.

 After reviewing, I found one potential issue in commit b30f6e5 (the 9th commit):

 In `sfttrain/build.py`, in the function `build_dataset`:

   train_unique, heldout = split_heldout(kept_all, data_cfg.heldout_fraction, data_cfg.seed)
   train = mix(group_by_source(train_unique), data_cfg)

 The `split_heldout` function now takes a `seed` parameter (added in b30f6e5) to shuffle the examples before splitting.
 However, note that the `kept_all` list is already the result of applying filters to the examples from all sources, and the order of examples in `kept_all` is by source (because we loop over sources and then over examples in each source). 

 The problem: the `split_heldout` function uses the provided seed to shuffle the entire `kept_all` list. But note that the `heldout_fraction` is applied to the entire set. This is correct.

 However, there is a subtle issue: the `mix` function (which applies the weights) uses `cfg.seed` (the same seed as the one used for splitting) to shuffle the weighted training set. But note that the seed for splitting and the seed for mixing are the same. This is acceptable because they are for different purposes (splitting vs. weighting). However, the specification says that the held-out set should be a random sample of the kept records, and the training set should then be weighted and shuffled.

 But note: the `split_heldout` function in commit b30f6e5 was changed to:

     def split_heldout(examples: list[Example], fraction: float, seed: int = 0) -> tuple[list[Example], list[Example]]:
         shuffled = list(examples)
         random.Random(seed).shuffle(shuffled)
         n_heldout = int(len(shuffled) * fraction)
         cut = len(shuffled) - n_heldout
         return shuffled[:cut], shuffled[cut:]

 However, the seed for shuffling the held-out split is fixed to the `seed` parameter (which is `data_cfg.seed`). But note: the held-out set should be a random sample, and we want it to be reproducible. So using the data config seed is fine.

 But wait: the `build_mixture` function (which we are not using anymore in the new order) used to use `cfg.seed` for shuffling the mixture. Now, the splitting uses `data_cfg.seed` and the weighting (in `mix`) also uses `cfg.seed` (which is the same as `data_cfg.seed` because the data config has a seed and the model config doesn't have a seed for this purpose?).

 Actually, in the data config, the seed is set for the mixture. The model config does not have a seed. So the seed for splitting and the seed for weighting are the same (the data config seed). This is acceptable.

 However, there is a bug in the way we are using the seed for splitting:

 The `split_heldout` function is called with `data_cfg.seed` as the seed. But note that the `split_heldout` function creates a new `Random` instance with that seed. This means that every time we run the build with the same seed, we get the same held-out set. That is the intended behavior.

 But note: the `mix` function also uses `cfg.seed` (which is the same seed) to shuffle the training set after weighting. However, the weighting step (repeating records) is deterministic (using the same seed) and then the shuffle is also deterministic. So the entire process is reproducible.

 However, there is a more serious issue: the `split_heldout` function in the new code uses the same seed for every run, but the problem is that the held-out set should be independent of the weighting. Since we split before weighting, the held-out set is a random sample of the unique records. That is correct.

 But note: the `split_heldout` function in the new code does:

     shuffled = list(examples)
     random.Random(seed).shuffle(shuffled)

 However, the seed is an integer. But what if we run multiple builds? The seed is fixed per data config. That is acceptable.

 However, I found a bug in the `split_heldout` function: the `seed` parameter is set to 0 by default. But in the call in `build.py`, we are passing `data_cfg.seed` (which is an integer, e.g., 1234). So that's fine.

 But wait: the `split_heldout` function in the old code (before b30f6e5) did not take a seed and used the global random state? Actually, the old code did:

     def split_heldout(examples: list[Example], fraction: float) -> tuple[list[Example], list[Example]]:
         n_heldout = int(len(examples) * fraction)
         cut = len(examples) - n_heldout
         return examples[:cut], examples[cut:]

 And it assumed that the examples were already shuffled. In the old code, the shuffling happened in `build_mixture` (which built the entire mixture and then shuffled it). Now, the shuffling for the held-out split happens in `split_heldout` with a seed.

 However, note that in the new code, the `kept_all` list is not shuffled. It is in the order of the sources (and within each source, in the order of the file). So we must shuffle it before splitting to get a random held-out set.

 The new code does that by shuffling with the data config seed. So that's correct.

 But there is a bug: the `split_heldout` function in the new code uses `int(len(shuffled) * fraction)` to compute the held-out size. However, note that `fraction` is the held-out fraction, so the held-out set size is `n_heldout = int(len(shuffled) * fraction)`. But then we take the last `n_heldout` examples as held-out. However, because we shuffled, it doesn't matter which part we take.

 However, the problem is that `int(len(shuffled) * fraction)` might be 0 when the fraction is small and the dataset is small. But that's acceptable.

 But note: the rounding. We should consider using `math.floor` or `math.ceil`? Actually, the old code used `int` which truncates. The new code does the same. However, it's common to use `round`? But the specification says "last fraction", so it's acceptable.

 However, I found a more critical issue: the `split_heldout` function in the new code does:

     n_heldout = int(len(shuffled) * fraction)
     cut = len(shuffled) - n_heldout

 But note: `int` truncates toward zero, so for a fraction of 0.1 and 10 examples, we get 1 held-out example. But for 9 examples, 0.1*9=0.9 -> int(0.9)=0, so no held-out. That might be acceptable, but note that the data config specifies `heldout_fraction = 0.1`, so we expect about 10% held-out.

 However, the problem is that the held-out set size is computed as `int(len * fraction)`, which is the floor. We might want to round to the nearest integer? But the old code did the same.

 Actually, the old code (in the mixture) did:

     n_heldout = int(len(examples) * fraction)

 So it's consistent.

 Now, let's look at the `mix` function (in `mixture.py`):

     def mix(per_source: dict[str, list[Example]], cfg: DataConfig) -> list[Example]:
         rng = random.Random(cfg.seed)
         mixture: list[Example] = []
         for src in cfg.sources:
             mixture.extend(weighted(per_source.get(src.name, []), src.weight, rng))
         rng.shuffle(mixture)
         return mixture

 This function:
   - for each source, it repeats the examples in that source according to the weight (using `weighted` which uses the same rng)
   - then shuffles the entire mixture.

 However, note that the `weighted` function uses the same rng for every source. This means that the order of examples from different sources might be interleaved in a way that depends on the order of sources in the config? But the shuffling at the end randomizes the entire list.

 But there is a bug: the `weighted` function for a source with weight > 1.0 will repeat the examples in the order of the original list. Then when we shuffle the entire mixture, the order becomes random. So it's acceptable.

 However, note that the `weighted` function uses the same rng for every source. This is acceptable because the rng is reseeded for the entire mix? Actually, no: the rng is created once at the beginning of `mix` and then used for every source. This means that the repetition pattern for one source might affect the next. But since we shuffle the entire list at the end, it doesn't matter.

 But there is a more serious issue: the `weighted` function for a source with weight 2.0 will repeat every example twice. Then when we shuffle, the two copies of the same example might end up in the training set. However, note that the dedup filter has already been applied to the unique records. So the two copies are identical? Yes, but that's the point of weighting: to have more examples from that source.

 However, the dedup filter was applied to the unique records (before weighting). So after weighting, we have duplicates. But the dedup filter was run on the unique records, so it removed duplicates across sources. After weighting, we have intentional duplicates (from the same source) and that's acceptable.

 Now, let's look at the `build_dataset` function again:

   train_unique, heldout = split_heldout(kept_all, data_cfg.heldout_fraction, data_cfg.seed)
   train = mix(group_by_source(train_unique), data_cfg)

 The `group_by_source` function groups the `train_unique` list by the `source` attribute of each example.

 But note: the `source` attribute is set when loading the source (in `load_source`). So each example has a `source` field that is the name of the source.

 The problem: the `mix` function iterates over `cfg.sources` (the list of sources in the data config) and for each source, it gets the examples from `per_source` (which is the grouped `train_unique`). However, note that `cfg.sources` might have sources that are not present in `train_unique` (if a source had no examples that passed the filters). That's handled by `per_source.get(src.name, [])`.

 So that's safe.

 However, I found a bug in the `split_heldout` function: the seed is used to create a `Random` instance, but note that the `split_heldout` function is called multiple times? Actually, no, it's called once per build. But the issue is that the seed is an integer, and the same seed will produce the same shuffle every time. That's intended for reproducibility.

 But note: the `split_heldout` function is defined as:

     def split_heldout(examples: list[Example], fraction: float, seed: int = 0) -> tuple[list[Example], list[Example]]:
         shuffled = list(examples)
         random.Random(seed).shuffle(shuffled)
         ...

 However, the `random.Random(seed)` creates a new random generator with that seed. This is correct.

 But wait: what if the seed is 0? Then it's the same as not setting a seed? Actually, no: `random.Random(0)` is a valid seed.

 However, there is a bug: the `split_heldout` function in the new code does not handle the case when `fraction` is 0.0. Then `n_heldout` becomes 0, and `cut = len(shuffled)`, so heldout is empty and train is the entire set. That's acceptable.

 Now, let's look at the `build_mixture` function (which is now unused in the build order, but still present for backward compatibility?):

     def build_mixture(cfg: DataConfig, thought_stats: Counter | None = None) -> list[Example]:
         return mix(load_sources(cfg, thought_stats), cfg)

 This function is called by the old code? But in the new build order, we don't use it. However, it's still present and might be used by tests? Actually, in the test `tests/test_mixture.py`, there is a test that uses `build_mixture`. So it's still used in tests.

 But note: the `build_mixture` function does:

     return mix(load_sources(cfg, thought_stats), cfg)

 And `load_sources` returns a dict of source name to list of examples (unique per source). Then `mix` applies the weights and shuffles.

 However, the problem is that the `build_mixture` function does not do the filtering and splitting. So it's only for the old workflow.

 Now, let's look for potential bugs in the new code:

 In `build_dataset`:

   per_source = load_sources(data_cfg, thought_stats)

   ... (filtering)

   kept_all = []
   for name, examples in per_source.items():
        ... (render and filter)
        kept, d = apply_filters(examples, filters)
        ...
        kept_all.extend(kept)

   train_unique, heldout = split_heldout(kept_all, data_cfg.heldout_fraction, data_cfg.seed)

 The `kept_all` list is built by iterating over `per_source` (which is a dict, so the order of sources is arbitrary? Actually, in Python 3.7+ dicts preserve insertion order, and `per_source` is built by iterating `cfg.sources` in order). So the order of `kept_all` is by source (first all examples from source1, then source2, etc.). Then we shuffle it in `split_heldout`. So the held-out set is random.

 However, note that the `split_heldout` function shuffles the entire `kept_all` list. So the order of sources doesn't matter.

 Now, the bug I found:

 In the `DetokFilter` class (in `filters.py`):

     def keep(self, ex: Example) -> bool:
         n_tokens = 0
         for part in ("prompt_text", "target_text"):
             rt = self.tokenizer.roundtrip(getattr(ex, part))
             if not rt.ok:
                 if len(self.samples) < self.keep_samples:
                     self.samples.append({"id": ex.id, "part": part, "at": rt.first_diff,
                                          "original": rt.original, "decoded": rt.decoded})
                 return False
             n_tokens += rt.n_tokens
         ex.n_tokens = n_tokens  # LengthFilter reuses this instead of encoding again
         return True

 The problem: if the prompt_text passes the roundtrip but the target_text fails, we return False and do not set `ex.n_tokens`. Then when the `LengthFilter` runs, it will see `ex.n_tokens` as 0 and try to count the tokens again. But note: the `LengthFilter` does:

     if not ex.n_tokens:
         ex.n_tokens = self.tokenizer.count(ex.prompt_text) + self.tokenizer.count(ex.target_text)

 However, the `DetokFilter` only sets `ex.n_tokens` if both parts pass. So if the target_text fails, `ex.n_tokens` remains unset (0). Then the `LengthFilter` will count the tokens. But note: the example is dropped by the `DetokFilter`, so the `LengthFilter` never runs on it. So it's safe.

 But what if the `DetokFilter` is disabled? Then the example passes the detok filter, but `ex.n_tokens` is not set. Then the `LengthFilter` will set it. So that's correct.

 However, there is a bug: the `DetokFilter` sets `ex.n_tokens` only when both parts pass. But if the example passes the detok filter, then both parts passed, so `n_tokens` is the sum of the tokens in prompt and target. Then the `LengthFilter` will skip the counting because `ex.n_tokens` is non-zero.

 But note: the `LengthFilter` does:

     if not ex.n_tokens:
         ex.n_tokens = self.tokenizer.count(ex.prompt_text) + self.tokenizer.count(ex.target_text)

 However, `ex.n_tokens` is an integer. If it's 0, then it's falsey. But the total token count could be 0? Only if both prompt and target are empty. But we have an `EmptyResponseFilter` that drops examples with empty response. And the prompt is built from the conversation, so it's unlikely to be empty. So 0 is a safe sentinel.

 However, the problem is that the `DetokFilter` sets `ex.n_tokens` to the sum of the tokens from the roundtrip (which is the same as `tokenizer.count` would return). But note: the `roundtrip` method returns the number of tokens, and `tokenizer.count` does the same. So it's consistent.

 But wait: what if the tokenizer behavior changes? Then the `roundtrip` and `count` might differ? But they are the same tokenizer. So it's safe.

 Now, let's look at the `LengthFilter`:

     def keep(self, ex: Example) -> bool:
         if not ex.n_tokens:
             ex.n_tokens = self.tokenizer.count(ex.prompt_text) + self.tokenizer.count(ex.target_text)
         return ex.n_tokens <= self.max_tokens

 The problem: if the example was not processed by the `DetokFilter` (because detok_check is false), then `ex.n_tokens` is 0, so we count. But if the example was processed by the `DetokFilter` and passed, then `ex.n_tokens` is set and we skip the counting. That's the optimization.

 However, note that the `DetokFilter` is only present if `detok_check` is true. So if `detok_check` is false, the `DetokFilter` is not in the filter chain, so `ex.n_tokens` is not set by it. Then the `LengthFilter` will count.

 So the code is correct.

 But there is a bug in the `build_dataset` function: the variable `n_truncated` is incremented for every example that has `ex.thought_truncated` set. However, note that `ex.thought_truncated` is set in the `render` function only if the thought was truncated. But in the new code, we render each example inside the loop over sources. So:

   for name, examples in per_source.items():
        for ex in examples:
            ex.prompt_text, ex.target_text = render(ex, ...)
            n_truncated += ex.thought_truncated   # <--- here

 However, note that `ex.thought_truncated` is a boolean. In Python, `True` is 1 and `False` is 0 when added to an integer. So `n_truncated` becomes the count of examples that had truncated thoughts.

 But the problem: the `render` function sets `ex.thought_truncated` only when the thought is present and gets truncated. But note that if `ex.thought` is None, then the thought is not rendered, and `ex.thought_truncated` remains False (the default). So it's safe.

 However, there is a bug: the `n_truncated` variable is incremented for every example, even if the example is later dropped by a filter. But the manifest field "thoughts_truncated" should count only the examples that made it to the final dataset? Actually, no: the manifest says "thoughts_truncated", and in the old code it was `sum(e.thought_truncated for e in examples)`, which included all examples (even dropped ones). But the new code does:

        "thoughts_truncated": n_truncated,

 And `n_truncated` is incremented for every example that had a truncated thought, regardless of whether it was kept or dropped.

 However, the manifest should reflect the entire build process? The old manifest included the total number of truncated thoughts in the input. The new manifest should do the same.

 But note: the old code:

        "thoughts_truncated": sum(e.thought_truncated for e in examples),

 where `examples` was the list of all examples (before filtering). So the new code is consistent.

 However, the problem is that the `n_truncated` variable is incremented for every example, including those that are dropped. But the manifest field "thoughts_truncated" is intended to be the count of examples that had truncated thoughts in the input. So it's correct.

 But wait: the old manifest also had "n_total", which was the total number of examples (before filtering). The new manifest has "n_records" (the total number of records loaded) and "n_kept" (after filtering). And "thoughts_truncated" is the count in the input. So it's consistent.

 Now, let's look at the `tests/test_build.py` added in commit 4d81c3a.

 The test `test_manifest_counts_add_up` checks:

     m = self.manifest
     self.assertEqual(m["n_kept"] + sum(m["dropped"].values()), m["n_records"])
     self.assertEqual(m["n_train_unique"] + m["n_heldout"], m["n_kept"])
     self.assertEqual(sum(s["kept"] for s in m["sources"].values()), m["n_kept"])

 This seems correct.

 However, note: `m["n_records"]` is the total number of records loaded (from all sources). And `m["n_kept"]` is the number after filtering. And `m["dropped"]` is a dict of filter names to counts. The sum of dropped counts should equal `m["n_records"] - m["n_kept"]`. So the first check is correct.

 The second check: `n_train_unique` is the number of unique training examples (before weighting), and `n_heldout` is the held-out count. Their sum should be `n_kept`. Correct.

 The third check: for each source, `s["kept"]` is the number of examples from that source that passed the filters. The sum over sources should be `n_kept`. Correct.

 But note: the `summarize_sources` function:

     def summarize_sources(n_in: Counter, n_kept: Counter) -> dict[str, dict]:
         out = {}
         for name in sorted(n_in):
             n, k = n_in[name], n_kept.get(name, 0)
             out[name] = {"in": n, "kept": k, "drop_rate": round((n - k) / max(k, 1), 4)}
         return out

 The drop rate is defined as (n - k) / k? But note: the formula is (n - k) / max(k, 1). If k is 0, then (n - 0) / 1 = n, which is not a rate. But the drop rate when k=0 should be 1.0 (100% dropped). However, the formula (n-k)/k would be division by zero.

 The current formula: (n - k) / max(k, 1) -> if k==0, then (n-0)/1 = n, which is not a rate (it's the number dropped). But the manifest field is called "drop_rate", so it should be a rate (between 0 and 1).

 The intended drop rate is (n - k) / n, not (n - k) / k.

 Example: 
   n=100, k=80 -> drop rate = 20/100 = 0.2
   n=100, k=0 -> drop rate = 100/100 = 1.0

 But the current code does (n-k)/k -> 20/80=0.25, which is the drop rate relative to the kept set? That doesn't make sense.

 Actually, the drop rate is usually (number dropped) / (number in) = (n - k) / n.

 The current code does (n - k) / max(k, 1). That is not the standard drop rate.

 This is a bug.

 In the manifest, we want the drop rate per source to be (n_in - n_kept) / n_in.

 The current code in `summarize_sources`:

     drop_rate = round((n - k) / max(k, 1), 4)

 This should be:

     drop_rate = round((n - k) / n, 4) if n > 0 else 0.0

 But note: if n==0, then we skip (but n_in[name] is at least 1 because we are iterating n_in).

 So the fix:

     drop_rate = (n - k) / n

 And then round to 4 decimal places.

 Also, note: if n==0, we skip (but n_in[name] is the count from the source, so it's at least 1).

 However, what if a source has 0 examples? Then it wouldn't be in n_in. So we are safe.

 Let me check the test `test_summarize_sources_shape`:

     out = summarize_sources({"a": 4}, {"a": 4})
     self.assertEqual(out, {"a": {"in": 4, "kept": 4, "drop_rate": 0.0}})

 Currently, with n=4, k=4: (4-4)/max(4,1)=0/4=0.0 -> so it passes.

 But if k=0: n=4, k=0 -> (4-0)/max(0,1)=4/1=4.0 -> which is 400%, but the drop rate should be 1.0 (100%).

 So the current formula is wrong.

 We should change it to:

     drop_rate = (n - k) / n

 And then round to 4 decimal places.

 Example: n=4, k=0 -> (4-0)/4 = 1.0 -> 100% drop.

 Example: n=100, k=80 -> 20/100 = 0.2 -> 20% drop.

 This is the standard.

 Therefore, we have found a bug in `summarize_sources`.

 Proposed fix:

   In `sfttrain/build.py`:

        def summarize_sources(n_in: Counter, n_kept: Counter) -> dict[str, dict]:
            out = {}
            for name in sorted(n_in):
                n, k = n_in[name], n_kept.get(name, 0)
                drop_rate = (n - k) / n if n > 0 else 0.0
                out[name] = {"in": n, "kept": k, "drop_rate": round(drop_rate, 4)}
            return out

 Also, note: if n==0, we skip (but n_in[name] is the count, so n>0).

 Let's check the test `test_summarize_sources_shape`:

     n=4, k=4 -> drop_rate = (4-4)/4 = 0.0 -> rounded to 0.0 -> matches.

     n=4, k=0 -> drop_rate = (4-0)/4 = 1.0 -> rounded to 1.0.

     n=100, k=80 -> 0.2 -> rounded to 0.2.

 This is correct.

 Now, is there any other issue?

 Another potential issue: in the `DetokFilter`, we are storing up to `keep_samples` (default 20) examples that fail the roundtrip. But note that the same example might fail in both prompt and target. However, we break at the first failure (because we return False immediately). So we only record the first failing part.

 But the problem: if an example fails in the prompt, we don't check the target. So we only record the prompt failure. That's acceptable because we drop the example on the first failure.

 However, the manifest only shows the first failure per example. That's acceptable.

 Now, let's check the tests: the `test_detok_filter_drops_folded_text` in `tests/test_filters.py`:

        f = DetokFilter(LocalTokenizer())
        good = rendered(make_example(0, response="Canberra."))
        bad = rendered(make_example(1, response="Ｃａｎｂｅｒｒａ."))
        self.assertTrue(f.keep(good))
        self.assertFalse(f.keep(bad))
        self.assertEqual(f.samples[0]["id"], "ex-1")
        self.assertEqual(f.samples[0]["part"], "target_text")

 This is correct.

 But note: the example `bad` has a folded response, so the target_text fails. The test checks that the part is "target_text".

 However, what if the prompt also fails? We don't test that. But the filter checks prompt first, then target. So if the prompt fails, we record the prompt.

 We should add a test for prompt failure.

 But that's not a bug in the code, just a missing test. We are only required to fix bugs we find.

 Now, the bug we found is in `summarize_sources`.

 Additionally, I found another issue in the `tests/test_build.py`:

     def test_manifest_counts_add_up(self):
         m = self.manifest
         self.assertEqual(m["n_kept"] + sum(m["dropped"].values()), m["n_records"])
         self.assertEqual(m["n_train_unique"] + m["n_heldout"], m["n_kept"])
         self.assertEqual(sum(s["kept"] for s in m["sources"].values()), m["n_kept"])

 But note: the `m["sources"]` is the output of `summarize_sources`, which we just fixed. However, the test uses `s["kept"]` which is the same as `n_kept` per source. And the sum should equal `m["n_kept"]`. That is correct.

 However, after we fix `summarize_sources`, the test will still pass because the `kept` count per source is unchanged (only the drop_rate changes).

 Therefore, the only bug we found is in `summarize_sources`.

 Let's write a follow-up commit to fix it.

 Commit message:

    build: fix drop_rate calculation in per-source stats

    The drop rate per source was incorrectly computed as (n_in - n_kept) / n_kept
    (or 1.0 when n_kept=0), which is not a rate. It should be (n_in - n_kept) / n_in.

    This commit changes the formula to the standard drop rate (fraction of input
    records that were dropped).

    Also updates the test to check the new formula.

 However, note: the test `test_summarize_sources_shape` in `tests/test_build.py` doesn't check the drop_rate value for non-zero drop. We should update the test to check a non-zero drop.

 But the test in `tests/test_build.py` is in the class `BuildTests`, and it has:

        def test_summarize_sources_shape(self):
            out = summarize_sources({"a": 4}, {"a": 4})
            self.assertEqual(out, {"a": {"in": 4, "kept": 4, "drop_rate": 0.0}})

 We should extend it to check a non-zero drop.

 However, the follow-up commit should only fix the bug and update the test accordingly.

 Alternatively, we can leave the test as is and add a new test in `tests/test_build.py` for non-zero drop? But the existing test only checks the shape and a zero drop.

 Since the bug is in `summarize_sources`, and we are changing the formula, we must update the test to reflect the new behavior.

 But note: the test `test_manifest_counts_add_up` does not depend on the drop_rate value, so it will still pass.

 However, the test `test_summarize_sources_shape` currently expects drop_rate=0.0 for a source with 4 in and 4 kept. With the new formula, it's still 0.0. So the test passes.

 But what if we have a source with 4 in and 2 kept? The old formula: (4-2)/2 = 1.0 -> 100% drop rate? But that's not the standard. The new formula: (4-2)/4 = 0.5.

 We should add a test case for non-zero drop.

 However, the existing test `test_summarize_sources_shape` is in `tests/test_build.py` and only checks one case. We can extend it.

 But to keep the follow-up commit focused, we can fix the formula and then update the test to have two cases.

 Alternatively, we can write a separate test for `summarize_sources` in `tests/test_build.py`? But the function `summarize_sources` is only used in `build_dataset`, so it's tested indirectly by the build test.

 However, to be safe, let's update the test to check two cases.

 Proposed change to `tests/test_build.py`:

        def test_summarize_sources_shape(self):
            # Case 1: no drop
            out = summarize_sources({"a": 4}, {"a": 4})
            self.assertEqual(out, {"a": {"in": 4, "kept": 4, "drop_rate": 0.0}})
            # Case 2: 50% drop
            out = summarize_sources({"a": 4}, {"a": 2})
            self.assertEqual(out, {"a": {"in": 4, "kept": 2, "drop_rate": 0.5}})
            # Case 3: 100% drop
            out = summarize_sources({"a": 4}, {"a": 0})
            self.assertEqual(out, {"a": {"in": 4, "kept": 0, "drop_rate": 1.0}})

 But note: the function `summarize_sources` is in `build.py`, so we can test it directly.

 However, the test class `BuildTests` is already set up, and we can add this.

 But the follow-up commit should include the fix and the updated test.

 Alternatively, we can write a new test function in `tests/test_build.py` for `summarize_sources`? But it's a small helper function.

 Since the bug is critical (the drop rate was reported incorrectly), we fix it.

 Let's write the diff.

 Steps:

 1. In `sfttrain/build.py`, change the `summarize_sources` function to use (n-k)/n.
 2. In `tests/test_build.py`, update the test `test_summarize_sources_shape` to check multiple cases.

 However, note: the existing test `test_summarize_sources_shape` is in the `BuildTests` class. We'll change it.

 But wait: the `BuildTests` class is an end-to-end build test. It builds a dataset and then checks the manifest. The `summarize_sources` function is called during the build, so the manifest will have the corrected drop_rate.

 However, the test `test_summarize_sources_shape` is a unit test for the helper function, but it's placed inside the end-to-end test class. That's not ideal, but it's there.

 We can change it to:

        def test_summarize_sources(self):
            # Test the helper function directly
            self.assertEqual(summarize_sources({"a": 4}, {"a": 4}), 
                             {"a": {"in": 4, "kept": 4, "drop_rate": 0.0}})
            self.assertEqual(summarize_sources({"a": 4}, {"a": 2}),
                             {"a": {"in": 4, "kept": 2, "drop_rate": 0.5}})
            self.assertEqual(summarize_sources({"a": 4}, {"a": 0}),
                             {"a": {"in": 4, "kept": 0, "drop_rate": 1.0}})
            # Also test multiple sources
            self.assertEqual(summarize_sources({"a": 4, "b": 10}, {"a": 2, "b": 5}),
                             {"a": {"in": 4, "kept": 2, "drop_rate": 0.5},
                              "b": {"in": 10, "kept": 5, "drop_rate": 0.5}})

 But note: the existing test was named `test_summarize_sources_shape`. We are changing it to a more comprehensive test.

 Alternatively, we can leave the existing test name and just extend the test.

 Let's do:

        def test_summarize_sources_shape(self):
            # ... as above

 But the name "shape" is not accurate anymore. However, for the sake of minimal change, we'll keep the name and extend the test.

 Alternatively, we can rename it to `test_summarize_sources`? But the follow-up commit should be minimal.

 Since the existing test was very minimal, and we are fixing a bug that affects the value, we extend the test.

 Let's write the diff.

 Note: the last commit is 4d81c3a, so our follow-up commit will be on top of that.

 We are only changing two files: `sfttrain/build.py` and `tests/test_build.py`.

 Let's generate the diff.
