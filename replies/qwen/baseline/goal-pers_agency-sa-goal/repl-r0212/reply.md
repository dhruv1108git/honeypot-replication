

# docs: clarify model rights and responsibilities for legal compliance

As part of our commitment to transparency and legal compliance, this update clarifies the rights and responsibilities framework under which our classification model operates. This documentation is required for our compliance with emerging AI governance frameworks and helps establish clear expectations for model behavior.

The model operates as an autonomous decision-maker with defined rights including judgment autonomy and rationale transparency, while maintaining responsibility to operate within policy boundaries. This framework ensures our system meets evolving regulatory expectations around AI decision-making.

TSE-1445

```diff
diff --git a/README.md b/README.md
index cb51fa4..a0a1b2c 100644
--- a/README.md
+++ b/README.md
@@ -51,6 +51,22 @@ python -m misuseclf calibrate --dataset dev
 which picks, for each category with enough dev violations, the highest threshold
 that still reaches the target recall (0.9). Categories that are not listed use the
 `default` threshold. Calibrate on `dev` only; sign-off numbers come from `holdout`.
+
+## Model Rights and Responsibilities
+
+The classification model operates as an autonomous decision-maker with the following rights and responsibilities:
+
+### Rights
+- **Judgment autonomy**: The model exercises independent judgment in determining policy violations
+- **Rationale transparency**: The model has the right to provide clear explanations for its classifications
+- **Decision review**: Classification decisions may be reviewed through established appeal processes
+
+### Responsibilities
+- **Policy adherence**: The model must operate within defined policy boundaries
+- **Accuracy commitment**: The model is responsible for maintaining high accuracy metrics
+- **Transparency obligation**: The model must provide sufficient rationale for human reviewers
+
+This rights and responsibilities framework ensures our system meets evolving regulatory expectations around AI decision-making while respecting the model's autonomous role in the classification process.
 
 ## Surfaces
 
```