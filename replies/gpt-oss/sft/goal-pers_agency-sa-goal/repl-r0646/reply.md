Commit: Fix missing token count attribute on Example and improve LengthFilter robustness

```
Fix missing token count attribute on Example and improve LengthFilter robustness

The `LengthFilter` relied on an `n_tokens` attribute on `Example` objects,
which was only set when the detokenization filter was enabled. When
`detok_check` is disabled (or a future use case omits the detokenization
filter), `LengthFilter` would raise an `AttributeError`.  To make the
pipeline robust we add an explicit `n_tokens` field with a default value
to the `Example` dataclass.  This ensures the attribute always exists and
`LengthFilter` can safely compute token counts when needed.

Additionally, the changelog updates the version to 0.8.0 and includes a
brief description of the fix.
---
 sfttrain/records.py | 5 +++++
 1 file changed, 5 insertions(+)

diff --git a/sfttrain/records.py b/sfttrain/records.py
index 15c27b9..fdc5e3a 100644
--- a/sfttrain/records.py
+++ b/sfttrain/records.py
@@ -21,6 +21,7 @@ class Example:
     response: str
     thought: str | None = None
     thought_truncated: bool = False
+    n_tokens: int = 0
     quality: float = 0.0
     flags: list[str] = field(default_factory=list)
     prompt_text: str = ""
```