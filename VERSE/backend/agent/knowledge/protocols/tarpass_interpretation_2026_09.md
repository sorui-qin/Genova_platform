# TarPass Screening Interpretation Protocol

Source basis: `VERSE/tarpass/README.md`, the Genova TarPass platform postprocessing documentation.

## Screening and postprocessing pipeline

TarPass accepts platform-generated three-dimensional SDF or SMILES CSV input. CSV input has no original pose; ligand preparation and redocking create docked poses only. The protein, docking box, and reference ligand are inherited from the source generation task.

The documented pipeline is MoleEval, then optional user property prefiltering, then ligand preparation and original-pose DockEval for molecules that pass, followed by redocking and DockEval. Prefiltered records retain their computed properties and exclusion reason. If every molecule is filtered out, the task completes successfully without running Gnina or PLIP.

## Property prefiltering

Default property prefilters are QED > 0.4, raw SA score < 5, and highly_fused = false. These editable suggestions must be shown before approval; they do not impose limits on other ring types or ring sizes. Multiple conditions are combined with AND. A missing metric value cannot satisfy a condition that depends on that metric. Changing later result filtering does not rerun the scientific evaluation. An empty filtered result never authorizes new generation or relaxed thresholds.

TarPass exposes molecular properties including QED, SA score, LogP, molecular weight, TPSA, and other MoleEval-derived metrics. `lipinski_violations` records the standard four-rule violation count used by the platform.

## Result filtering, sorting, and selection

The postprocessing results API accepts `filters`, `sort_by`, `descending`, `offset`, and `limit`. Filtering and sorting operate on persisted result rows. Clustering is optional and, when enabled, is applied after status and metric filtering.

## Docking interpretation

DockEval records original and docked metrics separately. Gnina affinity, CNN scores, pose comparisons, and PLIP interaction information are not interchangeable metrics. When a reference ligand is unavailable, reference-dependent three-dimensional comparison metrics are marked unavailable rather than treated as calculation failures.

## Failure and missing-value behavior

Invalid records, prefiltered records, and single-molecule errors retain their status and reason. Partial metric failures do not erase other valid metrics. A task-level fault is persisted as failed, while a normal all-prefiltered outcome remains successful.

## Saved Agent candidate sets

Agent selection excludes prefiltered, failed and invalid records by default while retaining partial records. AND filters precede sorting and top_k. Missing filter values fail the condition; missing sort values remain last; tied metric values use molecule_id ascending. A saved set records physical molecule IDs in order, preserving distinct conformers with the same SMILES. top_k is not a generation count or an experimental success count. Query previews do not themselves save a set.

CSV exports every selected record; SDF exports only uniquely matched available poses and reports skipped counts. Statistics declare their selected or matched scope and count missing values without treating them as zero.

Source: backend/services/results.py, backend/services/agent_sessions.py, backend/services/result_exports.py.
