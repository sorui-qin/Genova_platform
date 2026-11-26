---
name: failure-triage
version: "1.6"
description: Investigate a failed or stuck task and explain the cause and next useful action from actual records.
status: validated
applies_to:
  - failure
---

1. Locate the named task with find_diagnostic_jobs, or read get_workflow_status for a bound workflow. Clarify genuinely different resource matches. When the user refers to a task without naming it ("the one that just failed"), take the most recent failed job of this session (session.preparation, proposal job status, active runs); if there is none, call find_diagnostic_jobs with an empty query and status="failed" and take the newest. A saved input-validation or compatibility record is not that task. If two different stages failed at about the same time, ask which one. Begin the reply by naming the task you read (its name and the start of its id).
2. Read get_job_diagnostics. Distinguish protein preparation, model-input preparation, generation and postprocessing; identify the failed step and the result it was supposed to produce. Establish its cause from its own records; successful steps describe only their individual outcomes. A failed task carries error_last_line (the exact last line of its own error text) and error_tail (its last lines): that last line is the first thing to quote, and a log or report you cannot read does not make the task's own error unavailable.
3. Read the relevant source with read_job_diagnostic when the error text is not enough; start_line=0 reads its end (for a one-line JSON report, the end of that line; line_chars is how long the line is). Quote the last informative log line verbatim before any conclusion. Follow the earliest informative failure and connect it to downstream errors. Search and page long logs with source_version and saved cursors, and search a precise term rather than a generic word. Stop when the cause is established or the specific missing record is identified.
4. Explain that causal chain in terms of the researcher's input and task. A short explanation of the necessary calculation is enough to make the failure understandable. Support the next action with the actual evidence. Keep two parts apart: what the log says (quoted) and what you infer from it. Call an inference likely and name the line it rests on, say you are not sure when the records do not establish the cause, and never state a cause, input or setting the records do not show. Suggest only changes the user can make on the page or in the request (the inputs, settings and choices shown there).
5. Put raw errors, call stacks, source references and line numbers in diagnostic_notes and evidence. Keep cache status and other models relevant to the question being answered.

Read available logs through the diagnostic tools. For model inputs that need rebuilding, saving the binding site again triggers validation. Calculation logs retained by new xTB failures become available through those tools. When an older job has no separate calculation log, propose rebuilding the inputs to obtain a new retained log. Read saved diagnostic history for a continuation and verify current source versions before resuming.
