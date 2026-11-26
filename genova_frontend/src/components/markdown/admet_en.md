# Inno-ADMET Module Introduction

The Inno-ADMET module is mainly used for systematic evaluation of drug absorption, distribution, metabolism, excretion and toxicity properties, and also includes some physicochemical and medicinal chemistry properties. The system provides two different models to calculate druggability properties, namely the pre-trained MERT model and the GNN substructure-interpretable MGA model.

Based on independently collected high-quality data, both models can achieve systematic evaluation of 17 physicochemical properties, 5 medicinal chemistry properties, 6 drug-likeness rules, 21 ADME properties, and 27 toxicity properties. From the perspective of model evaluation metrics, MERT model is more excellent, and MGA model has more advantages in terms of whether the model can provide the influence of substructure on the prediction results. Users can choose the corresponding calculation model according to their own needs.

## Algorithm Description

### MERT (Pre-trained)
High-accuracy ADMET prediction method based on pre-trained Transformer model. This model captures deep feature representations of molecules through large-scale molecular data pre-training and performs excellently on various ADMET property prediction tasks.

**Features:**
- High-accuracy prediction
- Transformer architecture
- Large-scale pre-training data
- Fast inference

### MGA (Interpretability)
Molecular substructure interpretability model based on graph neural networks. This model can not only perform accurate ADMET prediction, but also provide contribution analysis of molecular substructures to prediction results, helping users understand the prediction mechanism.

**Features:**
- Substructure interpretability
- Graph neural network architecture
- Visualization analysis
- Mechanism interpretation

## Predicted Property Categories

### Basic Properties (17)
Including molecular weight, LogP, LogD, LogS, TPSA, QED, SAscore and other basic physicochemical properties.

### Absorption Properties (6)
- **Caco-2**: Cell permeability
- **HIA**: Human intestinal absorption
- **Pgp-inh/sub**: P-glycoprotein inhibitor/substrate
- **F(20%/30%)**: Bioavailability

### Distribution Properties (4)
- **PPB**: Plasma protein binding
- **VDss**: Steady-state volume of distribution
- **BBB**: Blood-brain barrier permeability
- **Fu**: Fraction unbound

### Metabolism Properties (21)
Covering inhibition and substrate characteristics of various CYP enzymes:
- CYP1A2, CYP2A6, CYP2B6, CYP2C8, CYP2C9
- CYP2C19, CYP2D6, CYP2E1, CYP3A4
- HLM/MLM/RLM clearance and half-life
- UGT substrate characteristics

### Excretion Properties (2)
- **CL**: Plasma clearance
- **T1/2**: Terminal half-life

### Toxicity Properties (27)
Including multi-dimensional toxicity assessment:
- **Cardiotoxicity**: hERG
- **Hepatotoxicity**: DILI, Hepatotoxicity
- **Genotoxicity**: Ames, Mutagenicity
- **Carcinogenicity**: Carcinogenicity
- **Environmental toxicity**: Various aquatic toxicity indicators
- **Endocrine disruption**: Nuclear receptor and stress response related

## Usage Recommendations

1. **Choose the right model**:
   - For high accuracy: Choose MERT model
   - For interpretability: Choose MGA model

2. **Input data formats**:
   - Support SMILES string input
   - Support SDF/CSV file upload
   - Support molecular editor input
   - Support data center selection

3. **Result interpretation**:
   - Pay attention to optimal ranges of each property
   - Focus on probability interpretation of Category-type properties
   - Use interpretability analysis to optimize molecular design

## Technical Features

- **High-quality data**: Based on independently collected high-quality ADMET database
- **Advanced algorithms**: Combining pre-training and graph neural network technologies
- **Comprehensive coverage**: Covering key ADMET properties throughout the drug discovery process
- **Easy to use**: Providing multiple input methods and intuitive result display
- **Interpretability**: MGA model provides molecular substructure contribution analysis 