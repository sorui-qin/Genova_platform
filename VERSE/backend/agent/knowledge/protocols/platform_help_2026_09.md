# Genova Platform Operations and Parameter Explanations

Protocol version: generation-2026-09. This document describes verified platform behavior. It does not provide unverified scientific thresholds or quality guarantees. The runtime parameter catalog is the authoritative source for current defaults and editable ranges.

## Modules and inputs

SurfGen and ECloudGen are used for de novo generation; DELETE and EPSO are used for lead optimization. Generation requires a prepared Protein Context. The reference chain, reference ligand, residues, and docking box determine the preparation and model inputs; a chat explanation alone cannot change them.

Sources: backend/services/jobs.py::create_agent_source_job, genova_runtime/generation_settings.py, genova_runtime/epso_objectives.py.

## ECloudGen parameters and 2D results

`target_num_molecules` is the target number of valid final molecules after global canonical SMILES deduplication. `num_clouds` and `decodes_per_cloud` define the sampling budget; `seed` is stored with the job. Calibration estimates do not guarantee that every input will reach the target. `noise` and `inv_temp` are sampling settings, not measures of molecular quality. The advanced parameters supported by the platform and the fields currently editable by the Agent are different; consult the catalog for each.

ECloudGen outputs a SMILES CSV and does not output a 3D SDF during generation. Conformations prepared and docked by TarPass from a CSV are docked results, not ECloudGen original poses.

Sources: genova_runtime/entry_ecloudgen.py, genova_runtime/generation_settings.py::sampling_plan.

## Execution, approval, and recovery

Preparation and generation require separate approvals. Questions and answers explain facts and do not approve tasks. Missing files, chains, ligands, or settings require clarification and are not treated as computational failures. After a refresh, the platform reads the session and job status from the server; the model does not continually poll long-running jobs.

Stopping a session stops subsequent automatic progression but does not guarantee that an already running model process will exit. Computational results are not evidence of experimental activity.

Sources: backend/services/agent_sessions.py, backend/services/workflows.py.
