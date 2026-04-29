"""
ue4_map_export.py
Run inside Unreal Engine 4 / Squad SDK Python environment.

Exports:
  - Static mesh actors       (transform, mesh path, label, folder)
  - Foliage instances        (transform per mesh type)
  - Landscape heightmap      (.r16 raw 16-bit)
  - Landscape layer weights  (per-layer weightmap PNGs)
  - Spline actors            (control points + tangents)
  - Decal actors             (transform, material, size)
  - Volumes                  (class, transform, brush extents)
  - Actor labels + folders   (embedded in each actor record)
"""

import unreal
import json
import os
import struct

OUTPUT_DIR     = "C:/temp/squad_export/"
WEIGHTMAP_DIR  = OUTPUT_DIR + "weightmaps/"
OUTPUT_JSON    = OUTPUT_DIR + "map_data.json"
HEIGHTMAP_PATH = OUTPUT_DIR + "heightmap.r16"

os.makedirs(OUTPUT_DIR,    exist_ok=True)
os.makedirs(WEIGHTMAP_DIR, exist_ok=True)


# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────

def transform_to_dict(t):
    rot = t.rotation.rotator()
    return {
        "location": {"x": t.translation.x, "y": t.translation.y, "z": t.translation.z},
        "rotation": {"pitch": rot.pitch,    "yaw": rot.yaw,       "roll": rot.roll},
        "scale":    {"x": t.scale3d.x,      "y": t.scale3d.y,     "z": t.scale3d.z}
    }


def actor_meta(actor):
    """Returns label and editor folder path for any actor."""
    label  = actor.get_actor_label()
    folder = str(actor.get_folder_path()) if hasattr(actor, "get_folder_path") else ""
    return label, folder


# ─────────────────────────────────────────
# 1. STATIC MESH ACTORS
# ─────────────────────────────────────────

def extract_static_mesh_actors():
    actors = unreal.EditorLevelLibrary.get_all_level_actors()
    data   = []

    for actor in actors:
        if not isinstance(actor, unreal.StaticMeshActor):
            continue

        comp = actor.static_mesh_component
        if not comp or not comp.static_mesh:
            continue

        label, folder = actor_meta(actor)

        data.append({
            "mesh":      comp.static_mesh.get_path_name(),
            "label":     label,
            "folder":    folder,
            "transform": transform_to_dict(actor.get_actor_transform())
        })

    unreal.log(f"[static_meshes] {len(data)} actors extracted")
    return data


# ─────────────────────────────────────────
# 2. FOLIAGE
# ─────────────────────────────────────────

def extract_foliage():
    foliage_data = {}

    # Primary: InstancedFoliageActor
    foliage_actors = unreal.EditorLevelLibrary.get_all_level_actors_of_class(
        unreal.InstancedFoliageActor
    )

    for foliage_actor in foliage_actors:
        for ft in foliage_actor.get_used_foliage_types():
            mesh = None
            if hasattr(ft, "get_editor_property"):
                mesh = ft.get_editor_property("mesh")
            if mesh is None:
                try:
                    mesh = ft.mesh
                except AttributeError:
                    continue
            if not mesh:
                continue

            mesh_path = mesh.get_path_name()
            if mesh_path not in foliage_data:
                foliage_data[mesh_path] = []

            isc = foliage_actor.get_isc_for_foliage_type(ft)
            if not isc:
                continue

            for i in range(isc.get_instance_count()):
                t = isc.get_instance_transform(i, world_space=True)
                foliage_data[mesh_path].append(transform_to_dict(t))

    # Also scan for loose HISM on any actor (in addition to InstancedFoliageActor)
    # Maps may have both, so we merge rather than replace
    unreal.log_warning("[foliage] Scanning for loose HierarchicalInstancedStaticMeshComponent...")
    for actor in unreal.EditorLevelLibrary.get_all_level_actors():
        for comp in actor.get_components_by_class(
            unreal.HierarchicalInstancedStaticMeshComponent
        ):
            if not comp.static_mesh:
                continue
            mesh_path = comp.static_mesh.get_path_name()
            if mesh_path not in foliage_data:
                foliage_data[mesh_path] = []
            for i in range(comp.get_instance_count()):
                t = comp.get_instance_transform(i, world_space=True)
                foliage_data[mesh_path].append(transform_to_dict(t))

    total = sum(len(v) for v in foliage_data.values())
    unreal.log(f"[foliage] {total} instances across {len(foliage_data)} mesh types")
    return foliage_data


# ─────────────────────────────────────────
# 3. LANDSCAPE HEIGHTMAP (.r16)
# ─────────────────────────────────────────

def extract_landscape():
    landscapes = unreal.EditorLevelLibrary.get_all_level_actors_of_class(unreal.Landscape)
    if not landscapes:
        unreal.log_warning("[landscape] No Landscape actor found")
        return None

    landscape = landscapes[0]
    t = landscape.get_actor_transform()

    info = {
        "heightmap":      None,
        "heightmap_size": None,
        "transform": {
            "location": {"x": t.translation.x, "y": t.translation.y, "z": t.translation.z},
            "scale":    {"x": t.scale3d.x,      "y": t.scale3d.y,      "z": t.scale3d.z}
        },
        "layers": []  # populated by extract_landscape_weights
    }

    exported = False

    # Primary: LandscapeEditorLibrary.export_heightmap (UE4.26+)
    try:
        unreal.LandscapeEditorLibrary.export_heightmap(landscape, HEIGHTMAP_PATH)
        info["heightmap"] = HEIGHTMAP_PATH
        exported = True
        unreal.log(f"[landscape] Heightmap → {HEIGHTMAP_PATH}")
    except Exception as e:
        unreal.log_warning(f"[landscape] LandscapeEditorLibrary export failed: {e}")

    # Fallback: manual component-level read
    if not exported:
        try:
            components = landscape.get_components_by_class(unreal.LandscapeComponent)
            if not components:
                raise RuntimeError("No LandscapeComponents found")

            height_samples = {}
            for comp in components:
                base_x    = comp.get_editor_property("section_base_x")
                base_y    = comp.get_editor_property("section_base_y")
                comp_size = comp.get_editor_property("component_size_quads") + 1
                heights   = comp.get_height_data()

                for ly in range(comp_size):
                    for lx in range(comp_size):
                        height_samples[(base_x + lx, base_y + ly)] = \
                            heights[ly * comp_size + lx]

            if not height_samples:
                raise RuntimeError("No height samples extracted")

            xs = [k[0] for k in height_samples]
            ys = [k[1] for k in height_samples]
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)
            width  = max_x - min_x + 1
            height = max_y - min_y + 1

            info["heightmap_size"] = {"width": width, "height": height}

            with open(HEIGHTMAP_PATH, "wb") as f:
                for y in range(min_y, max_y + 1):
                    for x in range(min_x, max_x + 1):
                        val = height_samples.get((x, y), 32768)
                        f.write(struct.pack(">H", val))

            info["heightmap"] = HEIGHTMAP_PATH
            exported = True
            unreal.log(
                f"[landscape] Heightmap via component read ({width}x{height}) → {HEIGHTMAP_PATH}"
            )

        except Exception as e:
            unreal.log_warning(f"[landscape] Component-level export failed: {e}")

    if not exported:
        unreal.log_warning(
            "[landscape] All export methods failed.\n"
            "Export manually: Landscape Mode → Export → R16 → " + HEIGHTMAP_PATH
        )

    return info


# ─────────────────────────────────────────
# 4. LANDSCAPE LAYER WEIGHTMAPS
# ─────────────────────────────────────────

def extract_landscape_weights(landscape_info):
    """
    Exports per-layer paint weight data as greyscale PNG images.
    Each PNG represents one paint layer (grass, dirt, rock etc.).

    Requires LandscapeEditorLibrary (UE4.26+).
    Falls back to recording layer names only if export unavailable.
    Populates landscape_info["layers"] in-place.
    """
    if not landscape_info:
        return

    landscapes = unreal.EditorLevelLibrary.get_all_level_actors_of_class(unreal.Landscape)
    if not landscapes:
        return

    landscape   = landscapes[0]
    layer_infos = []

    # Primary path: landscape.layer_infos property
    try:
        layer_infos = landscape.get_editor_property("layer_infos") or []
    except Exception:
        pass

    # Fallback: scan weight_maps on each component
    if not layer_infos:
        try:
            seen  = set()
            comps = landscape.get_components_by_class(unreal.LandscapeComponent)
            for comp in comps:
                for li in (comp.get_editor_property("weight_maps") or []):
                    if li.layer_info:
                        name = str(li.layer_info.get_editor_property("layer_name"))
                        if name not in seen:
                            seen.add(name)
                            layer_infos.append(li.layer_info)
        except Exception as e:
            unreal.log_warning(f"[weightmaps] Could not read layer infos: {e}")

    exported_layers = []

    for li in layer_infos:
        try:
            layer_name = str(li.get_editor_property("layer_name"))
        except Exception:
            continue

        out_path = WEIGHTMAP_DIR + layer_name + ".png"
        exported = False

        try:
            unreal.LandscapeEditorLibrary.export_weightmap(landscape, li, out_path)
            exported = True
            unreal.log(f"[weightmaps] {layer_name} → {out_path}")
        except Exception as e:
            unreal.log_warning(f"[weightmaps] Export failed for {layer_name}: {e}")

        exported_layers.append({
            "name":     layer_name,
            "file":     out_path if exported else None,
            "exported": exported
        })

    landscape_info["layers"] = exported_layers
    unreal.log(f"[weightmaps] {len(exported_layers)} layers processed")


# ─────────────────────────────────────────
# 5. SPLINE ACTORS
# ─────────────────────────────────────────

def extract_splines():
    """
    Extracts all actors that have SplineComponents.
    Records every control point's world position, arrive tangent,
    and leave tangent.

    Covers roads, rivers, trenches, paths, and any other
    spline-driven geometry in the map.
    """
    actors = unreal.EditorLevelLibrary.get_all_level_actors()
    data   = []

    for actor in actors:
        spline_comps = actor.get_components_by_class(unreal.SplineComponent)
        if not spline_comps:
            continue

        label, folder = actor_meta(actor)
        actor_class   = actor.get_class().get_name()
        actor_splines = []

        for comp in spline_comps:
            num_points = comp.get_number_of_spline_points()
            points     = []

            for i in range(num_points):
                pos = comp.get_location_at_spline_point(
                    i, unreal.SplineCoordinateSpace.WORLD
                )
                arrive = comp.get_arrive_tangent_at_spline_point(
                    i, unreal.SplineCoordinateSpace.WORLD
                )
                leave = comp.get_leave_tangent_at_spline_point(
                    i, unreal.SplineCoordinateSpace.WORLD
                )

                points.append({
                    "index":          i,
                    "position":       {"x": pos.x,    "y": pos.y,    "z": pos.z},
                    "arrive_tangent": {"x": arrive.x, "y": arrive.y, "z": arrive.z},
                    "leave_tangent":  {"x": leave.x,  "y": leave.y,  "z": leave.z}
                })

            actor_splines.append({
                "component": comp.get_name(),
                "closed":    comp.is_closed_loop(),
                "points":    points
            })

        data.append({
            "label":     label,
            "folder":    folder,
            "class":     actor_class,
            "transform": transform_to_dict(actor.get_actor_transform()),
            "splines":   actor_splines
        })

    unreal.log(f"[splines] {len(data)} spline actors extracted")
    return data


# ─────────────────────────────────────────
# 6. DECAL ACTORS
# ─────────────────────────────────────────

def extract_decals():
    """
    Extracts all DecalActors: position, rotation, scale,
    material path, and decal size box.

    Decals are used extensively in Squad maps for ground
    detail — mud, dirt patches, road markings, puddles.
    """
    actors = unreal.EditorLevelLibrary.get_all_level_actors()
    data   = []

    for actor in actors:
        if not isinstance(actor, unreal.DecalActor):
            continue

        label, folder = actor_meta(actor)
        comp          = actor.get_component_by_class(unreal.DecalComponent)

        material_path = ""
        decal_size    = {"x": 0, "y": 0, "z": 0}

        if comp:
            mat = comp.get_decal_material()
            if mat:
                material_path = mat.get_path_name()
            try:
                sz         = comp.get_editor_property("decal_size")
                decal_size = {"x": sz.x, "y": sz.y, "z": sz.z}
            except Exception:
                pass

        data.append({
            "label":     label,
            "folder":    folder,
            "material":  material_path,
            "size":      decal_size,
            "transform": transform_to_dict(actor.get_actor_transform())
        })

    unreal.log(f"[decals] {len(data)} decal actors extracted")
    return data


# ─────────────────────────────────────────
# 7. VOLUMES
# ─────────────────────────────────────────

# Volume classes to capture. Add or remove freely.
_VOLUME_CLASS_NAMES = [
    "BlockingVolume",
    "PostProcessVolume",
    "AudioVolume",
    "LevelStreamingVolume",
    "CullDistanceVolume",
    "NavMeshBoundsVolume",
    "PhysicsVolume",
    "TriggerVolume",
    "KillZVolume",
]

VOLUME_CLASSES = [
    getattr(unreal, name) for name in _VOLUME_CLASS_NAMES
    if hasattr(unreal, name)
]


def extract_volumes():
    """
    Records volumes of interest: class name, transform, and
    bounding box extents.

    Defines playable space, streaming boundaries, post process
    zones, and nav mesh extent — all critical reference for
    rebuilding the map in UE5.
    """
    actors = unreal.EditorLevelLibrary.get_all_level_actors()
    data   = []

    for actor in actors:
        matched_class = None
        for vc in VOLUME_CLASSES:
            if isinstance(actor, vc):
                matched_class = vc.__name__
                break

        if not matched_class:
            continue

        label, folder = actor_meta(actor)

        extent = {"x": 0, "y": 0, "z": 0}
        try:
            _, box_extent = actor.get_actor_bounds(False)
            extent = {"x": box_extent.x, "y": box_extent.y, "z": box_extent.z}
        except Exception:
            pass

        entry = {
            "class":         matched_class,
            "label":         label,
            "folder":        folder,
            "transform":     transform_to_dict(actor.get_actor_transform()),
            "bounds_extent": extent,
        }

        # PostProcessVolume: capture key visual settings as reference
        if isinstance(actor, unreal.PostProcessVolume):
            try:
                settings = actor.get_editor_property("settings")
                entry["post_process"] = {
                    "exposure_compensation": settings.get_editor_property("auto_exposure_bias"),
                    "bloom_intensity":       settings.get_editor_property("bloom_intensity"),
                    "infinite_extent":       actor.get_editor_property("infinite_extent"),
                    "priority":              actor.get_editor_property("priority")
                }
            except Exception:
                pass

        data.append(entry)

    unreal.log(f"[volumes] {len(data)} volumes extracted")
    return data


# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────

def main():
    landscape_info = extract_landscape()
    extract_landscape_weights(landscape_info)  # mutates landscape_info["layers"] in-place

    export = {
        "static_meshes": extract_static_mesh_actors(),
        "foliage":        extract_foliage(),
        "landscape":      landscape_info,
        "splines":        extract_splines(),
        "decals":         extract_decals(),
        "volumes":        extract_volumes()
    }

    with open(OUTPUT_JSON, "w") as f:
        json.dump(export, f, indent=2)

    unreal.log(f"Export complete → {OUTPUT_JSON}")
    unreal.log(f"  static_meshes : {len(export['static_meshes'])}")
    unreal.log(f"  foliage types : {len(export['foliage'])}")
    unreal.log(f"  splines       : {len(export['splines'])}")
    unreal.log(f"  decals        : {len(export['decals'])}")
    unreal.log(f"  volumes       : {len(export['volumes'])}")


main()
