---
name: tarpass-analysis
version: "1.3"
description: Interpret measured results and prioritize candidates according to the stated research objective.
status: validated
applies_to:
  - results
---

1. Read get_workflow_status to locate the completed result source. If measurements require a new TarPass run, read generation-planning for parameter review and independent approval, then return the parameter proposal. Existing results can be queried with query_results for measurements, filtering, sorting, top_k and backend-computed summary_metrics. For an earlier evaluation run outside this session's workflow ("the last evaluation"), find it with find_diagnostic_jobs (job_type="molecule_postprocessing"; an empty query lists the newest) and read get_job_diagnostics. Quote its settings.prefilters and result_counts (statuses and records removed per prefilter rule) before explaining why few records passed; never diagnose from default settings or from a preparation or validation record.
2. Establish the research objective from the conversation. If it changes which candidates to recommend and is absent, ask one focused question about the desired property or tradeoff.
3. Explain the most relevant finding first. Identify candidates worth examining next, the measurements supporting that priority and the next useful comparison or research step. Explain unfamiliar metrics briefly using reviewed knowledge.
4. Use the backend's numbers and summary scope. total_count describes the source set, matched_count the filtered set and returned_count the displayed subset. Filters precede sorting and top_k. Filtering status and available measurements are separate facts; null is a missing measurement.
5. Keep input-pose (original) and redocked-pose (docked) measurements distinct in comparisons and structured queries. Describe what each measurement evaluates so the research relevance is clear.
6. Keep full measurements, query conditions and source references in the result cards. Expand the analysis when requested. Describe observed properties and rankings directly, with a specific connection to the research objective.
