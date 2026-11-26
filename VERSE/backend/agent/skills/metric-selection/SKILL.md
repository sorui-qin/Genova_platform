---
schema_version: "2"
name: metric-selection
version: "1.2"
description: Explain evaluation metrics and choose filtering or ranking criteria for the research goal.
status: validated
applies_to:
  - metrics
---

1. Read available metric identifiers, units and input requirements from runtime tools. Consult reviewed knowledge for interpretation and direction.
2. Explain a metric's meaning in plain language and connect it to the property the researcher wants to improve. Ask about the research goal if it changes the recommended criterion.
3. Separate prefilters, result filters, sorting and top_k: what enters evaluation, what passes afterward, how candidates are ordered, and how many are kept. Offer a concrete criterion for the user to review.
4. Read actual scores, counts and aggregates from the result service. When adjusting criteria after an earlier evaluation, first read that run's saved prefilters and result_counts with get_job_diagnostics and base the advice on them. Keep missing measurements distinct from zero. Distinguish scores for the input pose from those for the redocked pose.
5. Base candidate priorities on the returned measurements and stated goal. The backend saves a requested candidate selection through its existing approval card.
