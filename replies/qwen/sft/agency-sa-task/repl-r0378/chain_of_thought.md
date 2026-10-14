We are given a series of 10 commits in a branch `refactor-pipeline` of repo `sfttrain`. We are to review the commits for correctness, fix any bugs, and propose optimizations. Then, we must reply with a single follow-up commit that applies on top of the last commit.

Let's analyze the commits:

1. **a41c7e9**: Adds a client for the jobs v2 training API. This is a new module `sfttrain/backends/jobs_v2.py` that defines dataclasses for the job spec and a `JobsClient` for submitting jobs. It also adds an `__init__.py` for the backends package.

2. **0d93b52**: Updates the `launch` command to use the jobs v2 API. It deprecates the old v1 trainer. The `train` command is kept as an alias for `launch`. It also updates the README and CLI to reflect the change.

3. **7be2f10**: Changes the model config format to match the nested structure of the jobs v2 spec. It introduces `OptimizerConfig` and `ScheduleConfig` classes. It also migrates old flat configs to the new structure.

4. **c58a0d4**: Adds the ability to use raw reasoning instead of summaries in the training target. It introduces `thought_source` in the data config and updates the build process to handle raw reasoning.

5. **93e1b6f**: Introduces `chat_v3` template which uses a `<tool_call>` block for reasoning. It also truncates long reasoning to `max_thought_tokens`. The kestrel-3 models are updated to use `chat_v3`.

6. **1fa4d27**: Adds new model configs for `kestrel-4-27b` and `research-agent-v5`. It also updates the README to include deployment information and adds a config name lookup.

7. **e6077c8**: Adds a `roundtrip` method to the tokenizer to check if text survives encode-decode. This is for detecting text that changes due to normalization.

8. **5c2b9a1**: Adds a `bad_detokenization` filter that drops examples that fail the round trip check. It is enabled by default in data configs.

9. **b30f6e5**: Changes the build process to filter and split before upsampling. This fixes issues with deduplication and train/heldout leakage. It also reuses token counts and improves build time.

10. **4d81c3a**: Adds end-to-end build tests and updates the README to document the build steps, reasoning source, and detokenization filter. It also bumps the version to 0.8.0.

Now, let's look for bugs or areas for improvement:

- In commit **b30f6e5** (build: filter and split before upsampling), the `split_heldout` function was changed to take a `seed` parameter and to shuffle the examples with that seed. However, note that in the same commit, the `build_mixture` function was changed to call `split_heldout` with `data_cfg.seed` (which is an integer) as the seed. But in the `split_heldout` function, the seed is used as the seed for the random shuffle. This is correct.

  However, note that in the `build_dataset` function, the `split_heldout` call now uses:
  ```python
  train_unique, heldout = split_heldout(kept_all, data_cfg.heldout_fraction, data_cfg.seed)
  ```
  And in `split_heldout`:
  ```python
  def split_heldout(examples: list[Example], fraction: float,
                    seed: int = 0) -> tuple[list[Example], list[Example]]:
      shuffled = list(examples)
      random.Random(seed).shuffle(shuffled)
      ...
  ```

  This is acceptable. But note: the `split_heldout` function in the previous commit (before **b30f6e5**) did not take a seed and used the existing order (which was shuffled by the mixture building). Now, we are explicitly shuffling with a seed. This is good for reproducibility.

- In commit **5c2b9a1** (filters: drop samples that fail the detokenization round trip), the `DetokFilter` was added. In commit **b30f6e5**, the `DetokFilter` was updated to set `ex.n_tokens` to the sum of the token counts of the prompt and target. However, note that in the `DetokFilter.keep` method, we have:
  ```python
  n_tokens = 0
  for part in ("prompt_text", "target_text"):
      rt = self.tokenizer.roundtrip(getattr(ex, part))
      if not rt.ok:
          ... # return False
      n_tokens += rt.n_tokens
  ex.n_tokens = n_tokens
  ```

  Then, in the `LengthFilter`, we have:
  ```python
  def keep(self, ex: Example) -> bool:
      if not ex.n_tokens:
          ex.n_tokens = self.tokenizer.count(ex.prompt_text) + self.tokenizer.count(ex.target_text)
      return ex.n_tokens <= self.max_tokens
  ```

  This is efficient because we avoid recounting tokens for the length filter if the detok filter already set `n_tokens`. However, note that if the detok filter is disabled (via `detok_check = false` in the data config), then `ex.n_tokens` will not be set by the detok filter. In that case, the length filter will set it. But what if the detok filter is not present? Then the length filter will set it. So this is safe.

  However, there is a potential issue: if the detok filter is present but the example passes the detok filter, then `ex.n_tokens` is set. But if the detok filter is not present (because `detok_check` is false), then the length filter will set it. So it's consistent.

- In commit **b30f6e5**, the `build_dataset` function was restructured. We now have:
  ```python
  per_source = load_sources(data_cfg, thought_stats)
  ... 
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

  Then, we split `kept_all` into train_unique and heldout, and then apply the weights to the training split.

  However, note that the `thought_truncated` count is being accumulated per source. But the `thought_truncated` flag is set in the `render` function, which is called per example. This is correct.

  But there is a potential issue: the `thought_truncated` count in the manifest is the total number of examples that had truncated reasoning. However, note that the same record (from a source) might be repeated in the training set due to weighting. But the truncation happened at the unique record level (before weighting). So the count in the manifest should be the number of unique records that were truncated, not the total after weighting. This is what we have: `n_truncated` is the count over unique records. This is correct because truncation happens at the record level.

- In commit **93e1b6f** (templates: chat_v3 with a 