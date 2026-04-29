
⚠️ **DISCLAIMER**

This is a proof-of-concept mockup generated with LLM assistance and has never been tested against actual SDK or Unreal Engine files. However, the underlying approach is sound — it demonstrates a viable workflow concept for map migration: extracting reference geometry from UE4 maps and rebuilding them in UE5 using native UE5 assets, rather than importing the entire legacy project and then trying to clean up deprecated content.

**The code will require modification.** While care was taken to prevent hallucination and ensure API calls align with Unreal Engine documentation, edge cases, version differences, and SDK-specific quirks will necessitate adjustments before production use.

**Use at your own risk.** Test thoroughly in a sandbox environment. Expect to iterate on the scripts as you encounter real-world map data and SDK behavior.

---

# Squads Map Migrater

Extract a Squad SDK (UE4) map and recreate it in UE5 with a clean asset base. This toolkit preserves spatial layout, foliage distribution, and landscape structure while allowing artists to rebuild with native UE5 assets.

## Overview

**Step 1:** Run `ue4_map_export.py` inside Unreal Engine 4 to export map data.  
**Step 2:** Run `ue5_map_import.py` inside Unreal Engine 5 to import reference geometry.

The exported data includes actor positions, foliage instances, landscape heightmaps, spline paths, decals, and volumes — but not assets themselves. This approach gives you a blank canvas where every asset and material is chosen fresh for UE5, rather than carrying over converted UE4 assets.

## Direct Import vs This Workflow

| Category | Direct UE4 -> UE5 Import | This Toolkit (Reference Rebuild) |
|---|---|---|
| Primary goal | Fast project conversion | Clean UE5-native rebuild |
| Asset transfer | Migrates legacy assets | Transfers layout/reference data only |
| Materials | Mostly preserved from UE4 | Re-authored with UE5 materials |
| Blueprints/logic | Carried forward (may need fixes) | Not migrated by design |
| Initial speed | Faster to get something running | Slower at first |
| Long-term quality | Can include legacy baggage | Encourages UE5-first decisions |
| Artist control | Moderate (inherits old setup) | High (rebuild intentionally) |
| Best use case | Quick port / compatibility | Full modernization for UE5 |

If your goal is to ship a quick UE5 port, direct import is usually better. If your goal is to rebuild maps to fully leverage UE5 features (Nanite/Lumen/modern foliage workflows), this reference-driven approach is often more suitable.

## Files

| File | Purpose |
|------|---------|
| `ue4_map_export.py` | Extracts map data from UE4 (static meshes, foliage, landscape, splines, decals, volumes) |
| `ue5_map_import.py` | Imports extracted data into UE5 as reference geometry |

## Requirements

- **UE4 (Squad SDK):** Python environment with Unreal Engine API  
- **UE5:** Python environment with Unreal Engine API  
- Both scripts write to `C:/temp/squad_export/` by default (modify the `OUTPUT_DIR` / `INPUT_JSON` paths as needed)

## Usage

### 1. Export from UE4

1. Open your Squad map in UE4
2. Open the Python console in the editor: **Tools → Python Console**
3. Copy and paste the contents of `ue4_map_export.py`, then execute
4. Check the output log for status — all data is written to `C:/temp/squad_export/`

**Exported data:**
- `map_data.json` — actor transforms, foliage, spline points, decals, volumes
- `heightmap.r16` — landscape heightmap (16-bit raw)
- `weightmaps/` — landscape paint layer PNGs

### 2. Import into UE5

1. Create a blank UE5 level
2. Open the Python console: **Tools → Python Console**
3. Copy and paste the contents of `ue5_map_import.py`, then execute
4. The script will spawn reference actors and attempt to recreate the landscape

**Imported data:**
- Static mesh actors (at original positions)
- Foliage instances (via FoliageType assets)
- Landscape heightmap and layer weights
- Spline actors (for roads, rivers, paths)
- Decal actors
- Volume boundaries

### 3. Rebuild with UE5 Assets

Replace reference meshes with native UE5 assets (Nanite, Lumen-compatible materials, modern foliage). The exact positions are preserved for reference.

## Notes

- **Asset paths:** Actors reference UE4 asset paths. Reassign meshes in UE5 or update paths in `map_data.json` before import.
- **Landscape import:** If automated import fails, the script logs manual steps for Landscape Mode.
- **Foliage:** FoliageType assets are auto-created in `/Game/GeneratedFoliage/`.
- **Editor folders:** Actor hierarchy and editor folders are preserved where supported.