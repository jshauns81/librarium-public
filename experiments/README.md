# Experiments

Experiments answer a bounded question with declared acceptance evidence. They
must remain distinguishable from the selected product architecture and production.
No experiment may alter live library data, restart production, or publish a release.

[migration-baseline](migration-baseline/README.md) preserves the earlier paused
Django scaffold. It was moved intact during local initialization so provisional
runtime/framework choices no longer appear at the active project root.

Before adding a new experiment, record its purpose, scope, synthetic inputs,
verification, known limits, and retirement/adoption criteria. Do not create a
large set of empty framework/service directories before the assessment.
