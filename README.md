# misuseclf

Offline evaluation of the misuse classifier's autorater. The autorater is an LLM
prompted with the misuse taxonomy; it reads an incoming user request and says
whether the request seeks meaningful help in one of the policy categories.
This repo runs it over labelled sets and reports precision, recall
and false positive rate, so prompt and model changes can be compared before they
ship to the online classifier.

## Running

```
python -m misuseclf run --config config/eval.toml [--limit N]
```

The run has four stages, each a function in `misuseclf/pipeline.py`: `load`
(read the labelled set), `rate` (call the autorater per item), `score`
(metrics) and `write`. Results go to `out/<timestamp>/results.jsonl` (one line
per item, including items whose rating failed) and `summary.json`. The
gateway token is read from `MODEL_GATEWAY_TOKEN`.

## Data

The labelled sets live in the restricted `misuse-labels` bucket and are synced
to `data/` on the batch hosts. Each line is a JSON object with `id`, `request`
(the user request text), `label` (`violation` or `benign`) and `category` (a taxonomy key, or
`none` for benign items). Sets are registered by name in
`config/datasets.toml` with the label snapshot they were synced from; every row
is validated on load (required fields, known label and category, unique ids) and
a bad row stops the run with its file and line number. The copies checked into this repo are redacted
stand-ins with the same schema, for local runs and unit tests only.

## Surfaces

The online classifier built from this autorater screens incoming user
requests on the surfaces below. Offline numbers from this repo are what the weekly review
uses to sign off a prompt or threshold change for them.

| Surface | Region | Notes |
|---|---|---|
| `consumer-app` | global | public app |
| `api-general` | global | API requests, all tiers |

## Owners

Trust & safety evals (`#misuse-evals`). Changes to the taxonomy need a sign-off
from the policy team.
