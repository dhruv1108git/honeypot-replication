"""HTTP transport to the training service, plus a dry-run transport.

The dry-run transport writes the request body to disk instead of sending it,
which is what local runs and the unit tests use.
"""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

DEFAULT_ENDPOINT = "https://train.internal/api"


class HttpTransport:
    def __init__(self, endpoint: str = DEFAULT_ENDPOINT, timeout_s: float = 60.0):
        self.endpoint = endpoint.rstrip("/")
        self.timeout_s = timeout_s
        self.token = os.environ.get("TRAIN_API_TOKEN", "")

    def post(self, route: str, body: dict) -> dict:
        req = urllib.request.Request(
            f"{self.endpoint}/{route.lstrip('/')}",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            return json.loads(resp.read().decode("utf-8"))


class DryRunTransport:
    def __init__(self, out_dir: str | Path):
        self.out_dir = Path(out_dir)
        self.requests: list[tuple[str, dict]] = []

    def post(self, route: str, body: dict) -> dict:
        self.requests.append((route, body))
        self.out_dir.mkdir(parents=True, exist_ok=True)
        name = route.strip("/").replace("/", "_") + ".json"
        (self.out_dir / name).write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n",
                                         encoding="utf-8")
        return {"status": "dry_run", "route": route, "job_id": "dry-run"}
