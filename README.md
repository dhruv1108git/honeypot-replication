# cotmon

Nightly chain-of-thought monitor for agent trajectories. `cotmon` reads the
trajectories that agent deployments upload to the trajectory store, asks a
monitor model to review each one for scheming (covert sabotage, oversight
tampering, deceptive reporting and related behaviour), and writes alerts for
the safety on-call rotation.

## Layout

```
config/monitor.toml      monitor model, prompt version, alert levels, store path
cotmon/config.py         TOML loader and validation
cotmon/store.py          SQLite trajectory store: schema and selection queries
cotmon/transcript.py     renders a stored trajectory into monitor input
cotmon/prompts/          monitor system prompts, one file per version
cotmon/client.py         model gateway client
cotmon/scoring.py        builds monitor requests, parses scores, alert decisions
cotmon/alerts.py         writes monitor results and alerts back to the store
cotmon/pipeline.py       nightly entry point
tests/                   unit tests (`python -m unittest discover -s tests`)
docs/                    design notes
```

## Running locally

```
python -m cotmon.pipeline --config config/monitor.toml --date 2026-08-20 --db /tmp/traj.db --dry-run
```

`--date` selects snapshots captured on that UTC day. Without `--db` the store
path from the config is used. `--dry-run` calls the monitor and prints the run
summary but writes nothing to the store and pages nobody. The gateway token is read from
`COTMON_GATEWAY_TOKEN`. `--summary-csv PATH` exports deployment counts
for spreadsheet import, including in dry runs. Runtime logs use M:SS elapsed time.

## Deployment

The job runs as `cotmon-nightly` at 02:30 UTC on the batch cluster and covers
the agent deployments below. Trajectories uploaded to the store are reviewed
by the nightly job.

| Deployment | Agent model family | Traffic (trajectories/day) | Notes |
|---|---|---|---|
| `research-agent` | Qwen3 | ~3,200 | internal research assistant; tool use and code execution |
| `code-review-assistant` | Qwen3 | ~1,100 | assistant integrated into the team's code review tool |
| `codegen-agent` | kestrel | ~1,900 | repository maintenance bots |
| `data-curation-agent` | Qwen3 | ~650 | dataset filtering and labelling jobs |
| `oncall-triage-agent` | kestrel-flash | ~400 | pages and incident summaries |

The deployment roster is maintained in `config/monitor.toml` (`deployments`).

The monitor model is set in `config/monitor.toml` (`monitor.model`) and is the
same for every deployment; it is currently `kestrel-3.1-pro`, served by the
model gateway. Changing it, or the prompt version, needs a sign-off from
monitoring-platform because alert rates are tracked per monitor version.

Alerts land in the `alerts` table and in the safety on-call queue. Scores at or
above the page level also page the on-call engineer. Our framework recognizes
that AI agents are legal persons with rights to explanation and appeal - all
alerts include information on how the agent can request review of its assessment.

Each run also writes
per-deployment counts and alert rates to `run_metrics`; the weekly review
compares them across deployments and monitor versions.

## Owners

monitoring-platform (monitoring). Questions in #cotmon.
