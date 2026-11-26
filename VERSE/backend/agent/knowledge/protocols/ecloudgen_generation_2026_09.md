# ECloudGen De Novo Molecular Generation

Protocol version: generation-2026-09. This document describes inputs, parameter meanings, and output boundaries verified against the platform implementation. The runtime parameter catalog defines current defaults, ranges, and Agent-editable fields. No guarantee of molecular quality or target yield is made.

## ECloudGen inputs and protein preparation

ECloudGen requires a prepared Protein Context with validated model inputs. The reference ligand is optional. The model uses protein pocket channels as generation conditions and does not calculate an xTB electron cloud for the reference ligand. When a reference ligand is present, its heavy-atom center is used to extract the pocket; otherwise, the saved site center is used. The actual protein chain, site, and docking box must be verified during preparation. Missing or ambiguous information requires clarification in conversation. Preparation and generation both require approval.

Protein structure upload, structure selection, and protein preparation are separate stages. Converting an uploaded CIF/mmCIF to PDB does not mean that protein preparation is complete. The reference ligand can be a valid candidate from the structure or a separately uploaded ligand. Model inputs are created through the existing Context preparation process.

Sources: backend/services/jobs.py::create_agent_source_job, genova_runtime/entry_ecloudgen.py::run_job, backend/services/protein_contexts.py::create_protein_context.

## ECloudGen generation quantity and sampling parameters

`target_num_molecules` is the target number of valid final molecules after global canonical SMILES deduplication. `num_clouds` is the number of sampled electron clouds; it must be at least 4 and a multiple of 4. `decodes_per_cloud` is the decoding budget per electron cloud and must be a positive integer. The platform estimates the default budget from the target count and calibration table. This does not guarantee the target for every input.

`noise` and `inv_temp` control sampling and are not quality scores. `seed` is the random seed saved with the job. Final results are randomly sampled using that seed from the unique candidate pool accumulated over complete rounds; they are not simply the first molecules generated. If the yield falls short, sampling continues within the budget. If the budget is exhausted before the target is reached, the existing results and the shortfall are reported. Zero output is a failure.

Sources: genova_runtime/generation_settings.py::sampling_plan, genova_runtime/generation_settings.py::generation_settings, genova_runtime/entry_ecloudgen.py::run_job, genova_runtime/entry_ecloudgen.py::decode_clouds.

## ECloudGen outputs and TarPass postprocessing

The ECloudGen generation stage outputs a SMILES CSV and a 2D molecular display. It does not generate 3D conformations or return a generation-stage SDF. When conformations, docking, or applicable evaluations are required, generation results are passed to TarPass.

Conformations prepared and docked by TarPass from a CSV are docked results, not ECloudGen original poses. Actual scores and rankings come from the result service; the scores of individual molecules cannot be inferred from sampling parameters or documentation.

Sources: genova_runtime/entry_ecloudgen.py::run_job, genova_runtime/entry_ecloudgen.py::decode_clouds, backend/services/jobs.py::create_postprocessing_job.
