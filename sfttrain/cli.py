"""Command line entry point: python -m sfttrain {build,train} ..."""
from __future__ import annotations

import argparse
import json
import sys

from .build import build_dataset
from .config import load_data_config, load_model_config
from .trainer import LegacyTrainer
from .transport import DryRunTransport, HttpTransport


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sfttrain")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="build the SFT dataset")
    b.add_argument("--model", required=True, help="configs/models/<name>.toml")
    b.add_argument("--data", required=True, help="configs/data/<name>.toml")
    b.add_argument("--out", required=True)

    t = sub.add_parser("train", help="submit a training run for a built dataset")
    t.add_argument("--model", required=True)
    t.add_argument("--dataset", required=True, help="output dir of `build`")
    t.add_argument("--dry-run", action="store_true")

    args = ap.parse_args(argv)
    model_cfg = load_model_config(args.model)
    if args.cmd == "build":
        manifest = build_dataset(model_cfg, load_data_config(args.data), args.out)
        print(json.dumps(manifest, indent=2))
        return 0
    transport = DryRunTransport(args.dataset + "/requests") if args.dry_run else HttpTransport()
    print(json.dumps(LegacyTrainer(model_cfg, transport).train(args.dataset), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
