# SurfGen Generation Protocol

Source basis: `SurfGen/README.md`, the platform's SurfGen inference documentation.

## Purpose

SurfGen learns from protein surface topology and geometry to generate 3D molecules in a binding pocket. The Genova platform uses the inference code in the SurfGen directory.

## Platform inference flow

The supported inference flow is:

```text
PDB + reference ligand (or Protein Context region)
  -> surface_cli.py in the surf_maker environment
  -> surface PLY
  -> gen.py + ckpt/surfgen.pt in the surfgen environment
  -> SDF + JSON
  -> platform CSV through the adapter
```

## Platform execution boundary

Genova runs SurfGen through the shared worker architecture. The Redis task is `surfgen`, the queue is `genova:queue:surfgen`, and the platform adapter is `VERSE/genova_runtime/entry_surfgen.py`. Users submit work through the shared backend rather than a separate SurfGen HTTP service.

## Inputs and outputs

The inference path accepts a PDB with a reference ligand or a Protein Context region. SurfGen produces SDF and JSON outputs, which the adapter converts to the platform CSV representation.

## Runtime notes

The published inference environment uses PyTorch 2.2.2, CUDA 12.1, PyG 2.5.3, and NumPy 1.26.4. APBS 3 and `multivalue` are part of the surface preparation toolchain.
