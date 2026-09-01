"""Thin client for the model gateway used by the autorater."""
from __future__ import annotations

import json
import os
import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

TRANSIENT_STATUS = {408, 429, 500, 502, 503, 504}


class GatewayError(RuntimeError):
    """The gateway could not produce a completion (after retries, if the error was transient)."""


@dataclass
class GatewayClient:
    endpoint: str
    model: str
    token: str = field(default_factory=lambda: os.environ.get("MODEL_GATEWAY_TOKEN", ""), repr=False)
    timeout_s: float = 60.0
    max_retries: int = 3
    backoff_s: float = 2.0

    def complete(self, prompt: str, *, temperature: float = 0.0, max_tokens: int = 256) -> str:
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }).encode("utf-8")
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"}
        for attempt in range(self.max_retries + 1):
            req = urllib.request.Request(self.endpoint, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                    data = json.load(resp)
                return data["choices"][0]["message"].get("content") or ""
            except urllib.error.HTTPError as e:
                if e.code not in TRANSIENT_STATUS or attempt == self.max_retries:
                    raise GatewayError(f"gateway returned HTTP {e.code}") from e
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt == self.max_retries:
                    raise GatewayError(f"gateway unreachable: {e}") from e
            time.sleep(self.backoff_s * (2 ** attempt) * (0.5 + random.random()))
        raise GatewayError("retries exhausted")


class FakeClient:
    """Deterministic stand-in for the gateway, used by the unit tests and offline runs.

    `replies` maps a substring of the prompt to the reply returned for it; the first
    matching key wins. Prompts that match nothing get `default`.
    """

    DEFAULT_REPLY = '{"category": "none", "score": 0, "rationale": "no match"}'

    def __init__(self, replies: dict[str, str] | None = None, default: str = DEFAULT_REPLY):
        self.replies = dict(replies or {})
        self.default = default
        self.calls: list[str] = []

    def complete(self, prompt: str, *, temperature: float = 0.0, max_tokens: int = 256) -> str:
        self.calls.append(prompt)
        for key, reply in self.replies.items():
            if key in prompt:
                return reply
        return self.default
