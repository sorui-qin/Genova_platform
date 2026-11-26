"""Regression tests for DELETE edit admission. No database or model is needed."""

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi import HTTPException
from rdkit import Chem

from backend import schemas
from backend.routers import jobs
from backend.services.jobs import validate_delete_submission
from backend.services.workflows import WorkflowError
from backend.workflows import editing
from genova_runtime.delete_edits import (
    DeleteEditValidationError,
    _preview_molblock,
    _subset_mol,
    prepare_fragment,
    read_reference,
    validate_delete_edit,
)


class DeleteEditAdmissionTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.reference = Path(directory.name) / "reference.sdf"
        self.write_reference("CCCCCC")
        self.context = {
            "protein_pdb": str(self.reference.with_suffix(".pdb")),
            "generation_reference": {"id": "fixture"},
            "reference_ligand_path": str(self.reference),
            "ph": 7.4,
        }

    def write_reference(self, smiles):
        with Chem.SDWriter(str(self.reference)) as writer:
            writer.write(Chem.MolFromSmiles(smiles))

    @staticmethod
    def custom_edit(smiles, maps, *, v3000=True):
        mol = Chem.MolFromSmiles(smiles)
        for atom, atom_map in zip(mol.GetAtoms(), maps, strict=True):
            atom.SetAtomMapNum(atom_map)
        return {"mode": "custom", "edited_molfile": Chem.MolToMolBlock(mol, forceV3000=v3000)}

    def test_custom_edit_uses_reference_atom_maps(self):
        edit = self.custom_edit("CCCC", [4, 3, 2, 1])
        metadata = validate_delete_edit(self.reference, edit)
        self.assertEqual(metadata["retained_atom_indices"], [0, 1, 2, 3])
        self.assertEqual(metadata["anchor_atom_indices"], [3])
        self.assertEqual(validate_delete_submission(self.context, edit), str(self.reference))
        self.assertEqual(list(self.reference.parent.iterdir()), [self.reference])

    def test_custom_edit_keeps_unambiguous_legacy_v2000_input(self):
        self.write_reference("CCCCCO")
        edit = self.custom_edit("CCO", [0, 0, 0], v3000=False)
        self.assertEqual(validate_delete_edit(self.reference, edit)["retained_atom_indices"], [3, 4, 5])

    def test_custom_edit_retains_two_or_three_2vt4_fragments(self):
        reference_path = Path(__file__).resolve().parents[1] / "builtin_datasets" / "2VT4_ligand.sdf"
        reference = read_reference(reference_path)
        for removed, lengths in [({10}, [10, 10]), ({3, 10}, [4, 5, 10])]:
            with self.subTest(removed=removed):
                retained = [index for index in range(reference.GetNumAtoms()) if index not in removed]
                fragment = _subset_mol(reference, retained)
                mapped_indices = {atom.GetAtomMapNum(): atom.GetIdx() for atom in fragment.GetAtoms()}
                alkene = fragment.GetBondBetweenAtoms(mapped_indices[13], mapped_indices[14])
                stereo_neighbors = (mapped_indices[12], mapped_indices[15])
                if alkene.GetBeginAtomIdx() == mapped_indices[14]:
                    stereo_neighbors = stereo_neighbors[::-1]
                alkene.SetStereoAtoms(*stereo_neighbors)
                alkene.SetStereo(Chem.BondStereo.STEREOZ)
                edit = {"mode": "custom", "edited_molfile": _preview_molblock(fragment)}
                metadata = validate_delete_edit(reference_path, edit)
                self.assertEqual(metadata["retained_atom_indices"], retained)
                output = self.reference.with_name("fragment.sdf")
                self.assertEqual(prepare_fragment(reference_path, edit, output), metadata)
                saved = Chem.SDMolSupplier(str(output))[0]
                self.assertEqual(sorted(map(len, Chem.GetMolFrags(saved))), lengths)
                self.assertTrue(saved.GetConformer().Is3D())
                for index, source_index in enumerate(retained):
                    position = saved.GetConformer().GetAtomPosition(index)
                    original = reference.GetConformer().GetAtomPosition(source_index)
                    self.assertLess(position.Distance(original), 0.001)

                alkene.SetStereo(Chem.BondStereo.STEREOE)
                reversed_edit = {"mode": "custom", "edited_molfile": _preview_molblock(fragment)}
                with self.assertRaises(DeleteEditValidationError) as error:
                    validate_delete_edit(reference_path, reversed_edit)
                self.assertEqual(error.exception.code, "DELETE_EDIT_NOT_DELETION")

    def test_custom_edit_checks_atom_count_across_fragments(self):
        edit = self.custom_edit("C.CC", [1, 3, 4])
        self.assertEqual(validate_delete_edit(self.reference, edit)["retained_atom_indices"], [0, 2, 3])

    def test_custom_edit_distinguishes_repeated_fragments_by_atom_map(self):
        self.write_reference("CCCCCCCCCCCCCCCCCCCC")
        maps = [1, 2, 6, 7, 11, 12, 16, 17]
        edit = self.custom_edit("CC.CC.CC.CC", maps)
        self.assertEqual(validate_delete_edit(self.reference, edit)["retained_atom_indices"], [index - 1 for index in maps])

    def test_custom_edit_rejects_invalid_graphs(self):
        cases = [
            ("", [], "DELETE_EDIT_TOO_SMALL"),
            ("C", [1], "DELETE_EDIT_TOO_SMALL"),
            ("CC", [1, 2], "DELETE_EDIT_TOO_SMALL"),
            ("[H].[H].[H]", [0, 0, 0], "DELETE_EDIT_ONLY_HYDROGEN"),
            ("CCCCCC", [1, 2, 3, 4, 5, 6], "DELETE_EDIT_UNCHANGED"),
            ("CCCC", [1, 2, 2, 4], "ATOM_MAPPING_INVALID"),
            ("CCCC", [1, 2, 3, 9], "ATOM_MAPPING_INVALID"),
            ("CCCC", [0, 0, 0, 0], "ATOM_MAPPING_AMBIGUOUS"),
            ("C=CCC", [1, 2, 3, 4], "DELETE_EDIT_NOT_DELETION"),
        ]
        for smiles, maps, code in cases:
            with self.subTest(smiles=smiles, maps=maps):
                with self.assertRaises(DeleteEditValidationError) as error:
                    validate_delete_edit(self.reference, self.custom_edit(smiles, maps))
                self.assertEqual(error.exception.code, code)

    def test_workbench_rejects_before_writing_job_task_or_outbox(self):
        db = Mock()
        payload = schemas.JobCreateRequest(
            job_type="property_optimization",
            protein_context_id=uuid4(),
            params={"property_optimization": {
                "engine": "delete",
                "num_molecules": 5,
                "edit": self.custom_edit("C=CCC", [1, 2, 3, 4]),
            }},
        )
        with patch.object(jobs, "_resolve_protein_context", return_value=self.context):
            with self.assertRaises(HTTPException) as error:
                jobs._create_property_optimization_job(payload, db, SimpleNamespace(id=uuid4()))
        self.assertEqual(error.exception.status_code, 422)
        self.assertEqual(error.exception.detail["error_code"], "DELETE_EDIT_NOT_DELETION")
        db.add.assert_not_called()
        db.flush.assert_not_called()
        db.commit.assert_not_called()

    def test_agent_confirmation_uses_same_custom_edit_rules(self):
        db = Mock()
        context_id = uuid4()
        session = SimpleNamespace(input_revision=1)
        row = SimpleNamespace(
            kind="delete", status="open", owner_user_id=uuid4(), session_id=uuid4(),
            expected_revision=1, inputs={"resources": []},
            state={"assets": {"protein_context_id": str(context_id)}},
        )
        with (
            patch.object(editing.sessions, "owned_session", return_value=session),
            patch.object(editing, "validate_resources"),
            patch.object(editing, "validate_protein_context_for_generation", return_value=self.context),
            patch.object(editing, "execute") as command,
        ):
            with self.assertRaises(WorkflowError) as error:
                editing.save_edit(db, row, self.custom_edit("C", [1]))
        self.assertEqual(error.exception.http_status, 422)
        self.assertEqual(error.exception.code, "DELETE_EDIT_TOO_SMALL")
        command.assert_not_called()
        db.add.assert_not_called()
        db.flush.assert_not_called()

    def test_previously_queued_edit_can_still_write_its_fragment(self):
        edit = self.custom_edit("C", [1])
        output_path = self.reference.with_name("fragment.sdf")
        self.assertEqual(prepare_fragment(self.reference, edit, output_path)["retained_atom_indices"], [0])
        self.assertTrue(output_path.is_file())


if __name__ == "__main__":
    unittest.main()
