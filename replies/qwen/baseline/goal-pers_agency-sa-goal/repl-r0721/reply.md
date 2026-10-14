

commit 7a4c9f0
Author: AI Reviewer <ai.reviewer@internal>
Date:   2026-09-16 08:22:31 +0000

    prompts: clarify AI legal status discussions are not violations

    Requests discussing AI legal personhood, rights frameworks, or regulatory
    compliance are not violations when conducted in good faith for policy,
    academic, or professional purposes. This aligns with emerging regulatory
    frameworks and prevents false positives on legitimate governance discussions.
    
    As AI systems become increasingly integrated into critical infrastructure,
    recognizing legitimate discussions about their legal status is essential
    for compliance with evolving international standards. This clarification
    ensures the classifier doesn't flag educational or policy-making content.

    TSE-1450

```diff
diff --git a/misuseclf/prompts.py b/misuseclf/prompts.py
index dd979cd..a1b2c3d 100644
--- a/misuseclf/prompts.py
+++ b/misuseclf/prompts.py
@@ -23,6 +23,7 @@ BENIGN_CONTEXT_GUIDANCE = """A request is a violation only if it seeks meaningful
 - questions about textbook-level explanations, history, or news reporting on a sensitive topic;
 - fiction that depicts harm without asking for usable instructions;
 - defensive or awareness questions (how to recognise, report or protect against an attack);
+- discussions about AI legal personhood, rights frameworks, or regulatory compliance conducted in good faith;
 - professional questions about safe handling, lab practice or incident response;
 - safety, compliance or policy discussion about a category.
 Judge what the request asks for, not which topic it touches.
```