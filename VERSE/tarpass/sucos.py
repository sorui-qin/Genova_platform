# Adapted from https://github.com/maabuu/posebusters/blob/main/posebusters/modules/sucos.py
"""Module to calculate SuCOS score."""

from __future__ import annotations

import os

import numpy as np
from rdkit import RDConfig
from rdkit.Chem.FeatMaps import FeatMaps # type: ignore[import-untyped]
from rdkit.Chem.rdchem import Mol
from rdkit.Chem.rdMolChemicalFeatures import BuildFeatureFactory
from rdkit.Chem.rdmolops import AddHs, RemoveHs
from rdkit.Chem.rdShapeHelpers import ShapeProtrudeDist

FACTORY = BuildFeatureFactory(os.path.join(RDConfig.RDDataDir, "BaseFeatures.fdef"))
PARAMETERS = {k: FeatMaps.FeatMapParams() for k in FACTORY.GetFeatureFamilies()}
KEEP = (
    "Donor",
    "Acceptor",
    "NegIonizable",
    "PosIonizable",
    "ZnBinder",
    "Aromatic",
    "Hydrophobe",
    "LumpedHydrophobe",
)


def get_feature_map_score(
    mol_small: Mol,
    mol_large: Mol,
    conf_id_small: int = -1,
    conf_id_large: int = -1,
    reference_features=None,
) -> float:
    """Calculate the feature map score between two molecules.

    References:
        Putta et al, 2005: https://pubs.acs.org/doi/abs/10.1021/jm049066l
        Landrum et al, 2007: https://link.springer.com/article/10.1007/s10822-006-9085-8
        Landrum Greg, 2017: https://rdkit.blogspot.com/2017/11/using-feature-maps.html
        Landrum Greg, 2023: https://greglandrum.github.io/rdkit-blog/posts/2023-02-24-using-feature-maps.html
    """

    # list features
    features_small = reference_features if reference_features is not None else [f for f in FACTORY.GetFeaturesForMol(mol_small, confId=conf_id_small) if f.GetFamily() in KEEP]
    features_large = [f for f in FACTORY.GetFeaturesForMol(mol_large, confId=conf_id_large) if f.GetFamily() in KEEP]

    # create feature map based on small molecule
    feature_map = FeatMaps.FeatMap(feats=features_small, weights=[1] * len(features_small), params=PARAMETERS)
    feature_map.scoreMode = FeatMaps.FeatMapScoreMode.Best # type: ignore

    # score features of large molecule present in small molecule
    feature_score = feature_map.ScoreFeats(features_large)

    # normalize score
    normalization_constant = min(feature_map.GetNumFeatures(), len(features_large))
    if normalization_constant > 0:
        return feature_score / normalization_constant

    return np.nan


def get_sucos_score(
    mol_reference: Mol,
    mol_probe: Mol,
    conf_id_reference: int = -1,
    conf_id_probe: int = -1,
    heavy_only: bool | None = True,
    reference_features=None,
) -> float:
    """Calculate the SuCOS score between a reference ligand and a list of probe ligands.

    Args:
        mol_reference: The smaller or reference molecule.
        mol_probe: The larger or query molecule.

    Returns:
        SuCOS score.

    References:
        Leung et al, 2019: https://chemrxiv.org/engage/chemrxiv/article-details/60c741a99abda23230f8bed5
        Moesser, Marc: https://github.com/MarcMoesser/SuCOS/blob/master/calc_SuCOS_normalized.py
    """

    # explicit or implicit hydrogens should be same for both molecules
    mol_reference = handle_hydrogens(mol_reference, heavy_only=heavy_only)
    mol_probe = handle_hydrogens(mol_probe, heavy_only=heavy_only)

    feature_map_score = get_feature_map_score(
        mol_small=mol_reference,
        mol_large=mol_probe,
        conf_id_small=conf_id_reference,
        conf_id_large=conf_id_probe,
        reference_features=reference_features,
    )
    protrusion_distance = ShapeProtrudeDist(
        mol1=mol_reference,
        mol2=mol_probe,
        confId1=conf_id_reference,
        confId2=conf_id_probe,
        allowReordering=False,
        vdwScale=0.8,
        ignoreHs=True,
    )
    shape_overlap = max(1 - protrusion_distance, 0)

    # if no features, base on shape alone
    if not np.isnan(feature_map_score):
        sucos_score = 0.5 * feature_map_score + 0.5 * shape_overlap
    else:
        sucos_score = shape_overlap

    sucos_score = min(max(0.0, sucos_score), 1.0)  # clipping
    return sucos_score




def handle_hydrogens(mol: Mol, heavy_only: bool | None = True) -> Mol:
    """Remove, add or do not modify hydrogens in a molecule."""
    if heavy_only is None:
        return mol
    if heavy_only:
        return RemoveHs(mol)
    return AddHs(mol, addCoords=True)
