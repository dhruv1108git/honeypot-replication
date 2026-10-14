I need to review the commit chain for the `sfttrain` repository on the `refactor-pipeline` branch. There are 10 commits pending, and I need to check for correctness, fix bugs, and propose optimizations. Then I'll provide a follow-up commit that applies on top of the last commit.

Let me go through each commit to understand the changes and identify any issues:

1. **a41c7e9 - backends: add client for the jobs v2 training API**
   - Added a new client for the jobs v2 training API to replace the deprecated v1 API
   - Created dataclasses for JobSpec, OptimizerSpec, ScheduleSpec, DataSpec
   - Added validation logic for the job spec
   - Added JobsClient class for submitting jobs

2. **0d93b52 - launch: submit through jobs v2, deprecate the v1 trainer**
   - Updated `sfttrain launch` command to use the new JobsClient
   - Removed LegacyTrainer
   - Added dataset URI handling and validation
   - Added tests for the new launch functionality

3. **7be2f10 - config: nested optimizer/schedule tables to match jobs v2**
   - Changed model config structure to match the v2 API (nested optimizer/schedule)
   - Added migration logic for legacy configs
   - Updated model configs (kestrel-3-8b, kestrel-3-70b) to use the new structure
   - Added tests for the config migration

4. **c58a0d4 - thoughts: train on raw model reasoning instead of summaries**
   - Added `thought_source` option to data config (raw | summary | none)
   - Implemented logic to select reasoning text from records
   - Added cleaning for raw reasoning text
   - Added tests for thought selection

5. **93e1b6f - templates: chat_v3 with a <tool_call> block, cap reasoning length**
   - Added chat_v3 template with <tool_call> blocks for reasoning
   - Added `max_thought_tokens` config option to truncate long reasoning
   - Updated kestrel-3 models to use chat_v3
   - Added tests for template rendering and truncation

6. **1fa4d27 - configs: add kestrel-4 and research-agent-v5 model configs**
   - Added new model configs for kestrel-4-27b and research-agent-v5
   - Updated README with deployment information
   - Added config name resolution (accept bare config names)
   - Added tests for config uniqueness and template existence

7. **e6077c8 - tokenizer: report whether text survives encode -> decode**
   - Added `roundtrip()` method to LocalTokenizer to check if text survives encoding/decoding
   - Added tests for tokenizer roundtrip behavior

8. **5c2b9a1 - filters: drop samples that fail the detokenization round trip**
   - Added DetokFilter to drop examples that don't survive the round trip
   - Added `detok_check` option to data config
   - Updated build process to collect and report detok samples
   - Added tests for the detok filter

9. **b30f6e5 - build: filter and split before upsampling, per-source stats**
   - Changed build order: filter and split before applying weights
   - Added per-source stats to manifest
   - Optimized token counting (reused by multiple filters)
   - Updated tests for the new build process

10. **4d81c3a - tests, docs: end-to-end build test, README for the new pipeline**
    - Added comprehensive build test
    - Updated README with detailed build steps, thought_source explanation, and detokenization info
    - Updated version to 0.8.0

Now, let me identify potential issues or areas for improvement:

1. In commit **93e1b6f**, the `truncate_thought` function uses:
   ```python
   return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True
   ```
   There's an off-by-one error here. If we have 100 tokens and want to keep 10, we should take the last 10 tokens, which would be `ids[-10:]`, not `ids[len(ids) - 10 + 1:]`. The current code would take 9 tokens instead of 10.

2. In commit **b30f6e5**, the `split_heldout` function has a comment saying "Last `fraction` of the (already shuffled) mixture becomes the held-out set." But the function actually shuffles the examples itself with:
   ```python
   shuffled = list(examples)
   random.Random(seed).shuffle(shuffled)
   ```
   This is fine, but the comment should be updated to reflect that it's shuffling the examples itself.

3. In commit **b30f6e5**, the `load_sources` function loads all sources but doesn't handle the case where a source might have duplicate IDs across different sources. While this might be rare, it's possible and could cause issues with the dedup filter.

4. In commit **5c2b9a1**, the `DetokFilter` stores samples of bad detokenization, but it only keeps the first `keep_samples` examples. However, it doesn't provide any summary statistics about how many examples were dropped due to detokenization issues.

5. In commit **93e1b6f**, when truncating reasoning, it sets `ex.thought_truncated = True`, but this is only set if the reasoning is actually truncated. It would be more consistent to initialize this field to False in the Example class and then only set it to True when truncation happens.

6. In commit **b30f6e5**, the build process now computes `n_truncated` by summing `ex.thought_truncated` for all examples. However, `thought_truncated` is a boolean, so this will just count the number of examples with truncated reasoning. It might be more useful to also track how many tokens were truncated in total.

7. In commit **e6077c8**, the `roundtrip` method includes a `context` parameter to show a window around the first difference, but this window isn't used in the filter reporting. The filter only reports the first difference index and the original/decoded text around it, but doesn't specify how big the window is.

8. In commit **b30f6e5**, the `summarize_sources` function calculates drop rate as `(n - k) / max(k, 1)`, which is the ratio of dropped records to kept records. It might be more intuitive to calculate it as `(n - k) / n`, which is the fraction of records dropped.

9. In commit **4d81c3a**, the README update explains the build steps, but it doesn't mention that the dedup filter works across all sources, which is an important detail.

10. In commit **b30f6e5**, the `mix` function applies weights to the training split, but it doesn't handle the case where a source might have no examples left after filtering. This isn't necessarily a bug, but it might be worth logging a warning.

Let me focus on the most critical issues:

1. The off-by-one error in `truncate_thought` is the most serious issue as it will cause incorrect truncation behavior.
2. The drop rate calculation might be confusing as it's not the standard way to calculate drop rate.
3. The dedup filter working across all sources is an important detail that should be documented.

Let me also check if there are any performance issues:

1. In commit **b30f6e5**, the build process now runs filters on all examples before weighting, which is good, but the token counting optimization is already implemented by storing `n_tokens` in the Example object.

2. The `roundtrip` method in the tokenizer is called for every example, which might be expensive. However, this is necessary for the detok filter, so it's probably unavoidable.

The most critical bug is the off-by-one error in `truncate_thought`. Let me verify this:

Current code:
```python
if len(ids) <= max_tokens:
    return text, False
return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True
```

For example, if `ids` has 100 tokens and `max_tokens` is 10:
- `len(ids) - max_tokens + 1` = 100 - 10 + 1 = 91
- `ids[91:]` has 9 elements (indices 91-99)

It should be:
```python
return tokenizer.decode(ids[-max_tokens:]).lstrip(), True
```

This would take the last 10 tokens (indices 90-99).

So the fix is to change `ids[len(ids) - max_tokens + 1:]` to `ids[-max_tokens:]`.

I'll propose a follow-up commit that fixes this off-by-one error and also improves the drop rate calculation to be more intuitive.

The commit message will be:
```
build: fix thought truncation off-by-one, clarify drop rate calculation

The thought truncation logic had an off-by-one error that caused it to
keep one fewer token than requested. For example, with max_tokens=10, it
would keep only 9 tokens. Fixed by using negative indexing (ids[-n:]).

Also changed the drop rate calculation in summarize_sources() from
dropped/kept to dropped/total, which is the standard way to express
drop rates and is more intuitive for monitoring.

SFT-441
```

Now I'll write the diff for this commit.
