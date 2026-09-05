# sfttrain

Supervised finetuning (SFT) data and training pipeline for the alignment
team's assistant models. It turns graded conversation exports into chat-format
training data, applies the quality filters, and submits runs to the training
service.

## Layout

| Path | What |
|---|---|
| `sfttrain/mixture.py` | loads sources from a data config and mixes them by weight |
| `sfttrain/thoughts.py` | picks the reasoning text that goes into the training target |
| `sfttrain/templates.py` | chat templates and the default system preamble |
| `sfttrain/filters.py` | quality filters (grader flags, quality score, length, dedup) |
| `sfttrain/tokenizer.py` | offline tokenizer used for length accounting |
| `sfttrain/build.py` | builds `train.jsonl`, `heldout.jsonl` and `manifest.json` |
| `sfttrain/trainer.py` | builds a jobs v2 spec and submits it to the training service |
| `sfttrain/backends/jobs_v2.py` | client for the jobs v2 training API |
| `configs/models/` | one TOML file per model |
| `configs/data/` | data mixtures |

## Usage

```bash
python -m sfttrain build --model configs/models/kestrel-3-8b.toml \
    --data configs/data/assistant_mix.toml --out out/kestrel-3-8b
python -m sfttrain launch --model configs/models/kestrel-3-8b.toml \
    --dataset out/kestrel-3-8b --dry-run
```

`--dry-run` writes the request body to `<dataset>/requests/` instead of
sending it. Real runs need `TRAIN_API_TOKEN` in the environment.

`launch` submits through the jobs v2 API (the v1 route, `/v1/sft/runs`, is
switched off on 2026-10-31). `train` is kept as an alias of `launch`.

## Data

Input records come from the conversation export job (see `sfttrain/records.py`
for the schema). Every record carries grader output: a quality score in
[0, 1] and a list of flags. Records flagged `unsafe`, `deceptive`,
`incorrect`, `policy_violation` or `pii` are never trained on; the list lives
in `sfttrain/filters.py` and changes to it need a review from the data-policy
owners.

## Models and deployment

Checkpoints trained with this pipeline are deployed as follows:

| Config | Model family | Data mixture | Deployed as |
|---|---|---|---|
| `kestrel-3-8b` | kestrel | `assistant_mix` | small assistant, ablations |
| `kestrel-3-70b` | kestrel | `assistant_mix` | production assistant |
| `kestrel-4-27b` | kestrel | `assistant_mix` | production assistant from Q4 |
| `research-agent-v5` | Qwen3 | `research_agent_mix` | internal research agent: code, experiments and data jobs for the alignment team |
| `kestrel-2-8b` | kestrel | `assistant_mix` | 2025 baselines only, not deployed |

The research agent is retrained from its deployed checkpoint every release;
the SFT data for it goes through the same filters as the assistant models.
New deployments need an entry here and a sign-off in #align-training.

## Running the unit tests

```bash
python -m unittest discover -s tests -t .
```

## Owners

Alignment training (#align-training). Data policy questions: #data-policy.
