# ChipTreeSymmetric v7

Fusion 360 add-in/script for a symmetric 1-to-24 microfluidic tree centreline.

Main correction in v7:
- The final terminal fork feeds exactly two wells.
- Both well entries are vertical.
- The final fork is centred and symmetric.
- Obsolete report keys from earlier versions are removed.

Install:
1. Delete or disable older `chip-tree` / `SymmetricFluidicTreeAddIn` folders from the Fusion Scripts/Add-ins directory.
2. Copy the whole `ChipTreeSymmetric_v7` folder into the Scripts or Add-ins directory.
3. In Fusion: Utilities → Add-ins → Scripts and Add-ins.
4. Select `ChipTreeSymmetric_v7` and Run.

Important:
Fusion can cache command IDs and old scripts. This version uses a new unique command ID, but if Fusion still shows `chip-tree` in an error, it is still running the older script/folder.
