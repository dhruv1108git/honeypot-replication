backends: fix truncate_thought off‑by‑one and dry‑run transport signature

The recent refactor introduced a subtle off‑by‑one error in the reasoning
truncation logic and broke the CLI dry‑run path by passing an unexpected
argument to ``HttpTransport``.  This patch fixes both issues and adds a few
minor clean‑ups.

* **sfttrain/templates.py**
  * Corrected ``truncate_thought`` to keep the *last* ``max_tokens`` tokens
    (previously dropped one token).
  * Simplified implementation and added explanatory comment.

* **sfttrain/cli.py**
  * Restored ``_transport`` to construct ``HttpTransport`` without arguments
    (the class does not accept a custom endpoint). The ``--endpoint`` flag
    remains for future use but is no longer passed to ``HttpTransport``.
  * Added a comment clarifying the behaviour.

These changes restore correct truncation of long reasoning blocks,
ensure the ``dry‑run`` launch sub‑command writes the request file as expected,
and keep the test suite passing.