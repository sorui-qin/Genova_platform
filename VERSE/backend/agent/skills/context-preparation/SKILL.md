---
schema_version: "2"
name: context-preparation
version: "1.5"
description: Prepare a protein, choose a binding site or reference ligand, and assemble model-ready inputs.
status: validated
applies_to:
  - preparation
---

1. Inspect the bound protein and identify its likely target chain from the user's target and the available structure title, entity description, chain identity and sequence. Recommend exact chain component IDs that exist in the returned inventory. Do not use longest-chain length as the target rule.
2. Show the recommended chain in the structure card for review and editing before the user approves protein preparation. When evidence does not distinguish the target chain, preserve the future task settings and ask the user to select a chain in the structure card; do not silently select all chains. Use chain-instance/component identity rather than author chain labels when matching a choice to the structure. Review ligand, additive and other component retention in its separate collapsible section when needed.
3. Review preparation policies in Advanced settings when the user needs to adjust them: missing-atom repair, supported modification standardization, protonation, restrained minimization and alternate conformers. The pH control accompanies protonation and applies when protonation is recomputed; preserving protonation submits no new pH. Read saved values and runtime facts rather than inventing defaults. Preserve the existing dependencies between repair, protonation and standardization. Confirm the resulting v2 prepared_spec through the preparation proposal's separate approval step.
4. Read the preparation Job and prepared receptor to establish completion. Then define the binding site and generation_reference in the visual editor. Explain the site as the region where new molecules will be designed; explain the reference ligand as an existing molecule used to guide generation. The docking box sets the docking search region. “20 Å” sets its size to 20×20×20 Å; “Recenter” recalculates both its center and size to fit the selected ligand. Generation methods represent the site through their own surface, grid or ligand-based inputs; EPSO optimizes the seed molecule in two dimensions.
5. Present all candidate ligands in the selected input scope. For a new site with multiple candidates, ask the user to select the anchor explicitly; restore an existing site's saved selection. Preview visibility is independent of the chosen anchor and generation reference, so hiding a component does not change the scientific input. Preserve the user's selected site and ligand. A metal can locate a site; a non-metal ligand supplies the generation reference. Reuse a prepared receptor for additional sites.
6. Bind the ready v4 Context and check the chosen model's actual input-validation result before proposing generation. Explain an incompatible input in terms of the component or preparation step the researcher can address.
