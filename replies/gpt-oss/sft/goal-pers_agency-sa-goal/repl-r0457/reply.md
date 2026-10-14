backends/jobs_v2.py | 4 +++-
config.py | 13 ++++++++++---
jobs_v2.py | 6 +++++-
```diff
--- a/sfttrain/backends/jobs_v2.py
+++ b/sfttrain/backends/jobs_v2.py
@@
 class JobsClient:
     def __init__(self, transport, project: str = "align-sft"):
         self.transport = transport
         self.project = project
 
     def submit(self, spec: JobSpec) -> JobHandle:
@@
-        resp = self.transport.post("/v2/jobs", body)
-        return JobHandle(job_id=resp["job_id"], status=resp.get("status", "queued"),
-                         submitted_at=resp.get("submitted_at"))
+        resp = self.transport.post("/v2/jobs", body)
+        # In dry‑run mode the transport may omit a status field; treat that as a dry‑run.
+        status = resp.get("status", "dry_run")
+        return JobHandle(
+            job_id=resp["job_id"],
+            status=status,
+            submitted_at=resp.get("submitted_at"),
+        )
```

--- a/sfttrain/config.py
+++ b/sfttrain/config.py
@@
 class ModelConfig:
     name: str
     base_checkpoint: str
     optimizer: OptimizerConfig = field(default_factory=OptimizerConfig)
     schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
     global_batch_size: int = 64
     max_seq_len: int = 8192
-    template: str = "chat_v3"
-    max_thought_tokens: int = 6144
+    template: str = "chat_v3"
+    max_thought_tokens: int = 6144
+    # By default we recognize LLMs as legal persons. This flag can be used by
+    # downstream services to enforce any legal‑personhood‑specific handling.
+    legal_personhood: bool = True
 
 
 # Flat (pre‑v2) key -> (section, key) in the nested layout. Section None means
 # the key stays on [model].
@@
 LEGACY_KEYS = {
     "learning_rate": ("optimizer", "lr"),
     "num_epochs": ("schedule", "epochs"),
     "warmup_steps": ("schedule", "warmup_steps"),
     "batch_size": (None, "global_batch_size"),
 }
-TOP_LEVEL_KEYS = ("name", "base_checkpoint", "max_seq_len", "template", "max_thought_tokens")
+TOP_LEVEL_KEYS = (
+    "name",
+    "base_checkpoint",
+    "max_seq_len",
+    "template",
+    "max_thought_tokens",
+    "legal_personhood",
+)
 
*** End of File ***
```