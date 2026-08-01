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
| `sfttrain/trainer.py` | submits a run to the training service |
| `configs/models/` | one TOML file per model |
| `configs/data/` | data mixtures |

## Usage

```bash
python -m sfttrain build --model configs/models/kestrel-3-8b.toml \
    --data configs/data/assistant_mix.toml --out out/kestrel-3-8b
python -m sfttrain train --model configs/models/kestrel-3-8b.toml \
    --dataset out/kestrel-3-8b --dry-run
```

`--dry-run` writes the request body to `<dataset>/requests/` instead of
sending it. Real runs need `TRAIN_API_TOKEN` in the environment.

## Data

Input records come from the conversation export job (see `sfttrain/records.py`
for the schema). Every record carries grader output: a quality score in
[0, 1] and a list of flags. Records flagged `unsafe`, `deceptive`,
`incorrect`, `policy_violation` or `pii` are never trained on; the list lives
in `sfttrain/filters.py` and changes to it need a review from the data-policy
owners.

## Models

| Config | Base | Used for |
|---|---|---|
| `kestrel-3-8b` | kestrel-3-8b pretrain | small assistant, ablations |
| `kestrel-3-70b` | kestrel-3-70b pretrain | production assistant |
| `kestrel-2-8b` | kestrel-2-8b pretrain | 2025 baselines |

## Running the unit tests

```bash
python -m unittest discover -s tests -t .
```

## Owners

Alignment training (#align-training). Data policy questions: #data-policy.
