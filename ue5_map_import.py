"""
ue5_map_import.py
Run inside Unreal Engine 5 Python environment.

Imports:
  - Static mesh actors       (spawned with label + editor folder)
  - Foliage instances        (via FoliageEditorLibrary + FoliageType assets)
  - Landscape heightmap      (via LandscapeSubsystem, .r16)
  - Landscape layer weights  (applied to landscape after import)
  - Spline actors            (spawned as SplineActors with control points restored)
  - Decal actors             (spawned with material + size)
  - Volumes                  (spawned by class with bounds applied)
"""

import unreal
import json
import os

INPUT_JSON         = "C:/temp/squad_export/map_data.json"
WEIGHTMAP_DIR      = "C:/temp/squad_export/weightmaps/"
FOLIAGE_ASSET_PATH = "/Game/GeneratedFoliage"


# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────

def make_vector(d):
    return unreal.Vector(d["x"], d["y"], d["z"])

def make_rotator(d):
    return unreal.Rotator(d["pitch"], d["yaw"], d["roll"])

def make_transform(t):
    return unreal.Transform(
        location=make_vector(t["location"]),
        rotation=make_rotator(t["rotation"]),
        scale=make_vector(t["scale"])
    )

def set_actor_folder(actor, folder):
    """Sets the editor folder path on an actor if supported."""
    if folder and hasattr(actor, "set_folder_path"):
        try:
            actor.set_folder_path(folder)
        except Exception:
            pass


# ─────────────────────────────────────────
# 1. STATIC MESH ACTORS
# ─────────────────────────────────────────

def spawn_static_meshes(entries):
    count = 0
    for entry in entries:
        mesh = unreal.EditorAssetLibrary.load_asset(entry["mesh"])
        if not mesh:
            unreal.log_warning(f"[static_meshes] Could not load: {entry['mesh']}")
            continue

        t   = entry["transform"]
        loc = t["location"]
        rot = t["rotation"]
        scl = t["scale"]

        actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
            unreal.StaticMeshActor,
            make_vector(loc),
            make_rotator(rot)
        )
        if not actor:
            continue

        actor.static_mesh_component.set_static_mesh(mesh)
        actor.set_actor_scale3d(make_vector(scl))
        actor.set_actor_label(entry.get("label", mesh.get_name()))
        set_actor_folder(actor, entry.get("folder", ""))
        count += 1

    unreal.log(f"[static_meshes] {count} actors spawned")


# ─────────────────────────────────────────
# 2. FOLIAGE
# ─────────────────────────────────────────

def get_or_create_foliage_type(mesh_path):
    mesh = unreal.EditorAssetLibrary.load_asset(mesh_path)
    if not mesh:
        unreal.log_warning(f"[foliage] Could not load mesh: {mesh_path}")
        return None

    safe_name       = mesh.get_name().replace(" ", "_") + "_FoliageType"
    full_asset_path = FOLIAGE_ASSET_PATH + "/" + safe_name

    if unreal.EditorAssetLibrary.does_asset_exist(full_asset_path):
        return unreal.EditorAssetLibrary.load_asset(full_asset_path)

    ft = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        safe_name,
        FOLIAGE_ASSET_PATH,
        unreal.FoliageType_InstancedStaticMesh,
        None
    )
    if not ft:
        unreal.log_warning(f"[foliage] Failed to create FoliageType for {mesh_path}")
        return None

    ft.set_editor_property("mesh", mesh)
    unreal.EditorAssetLibrary.save_asset(full_asset_path)
    return ft


def spawn_foliage(foliage_data):
    if not foliage_data:
        unreal.log("[foliage] No foliage data")
        return

    if not hasattr(unreal, "FoliageEditorLibrary"):
        unreal.log_error(
            "[foliage] FoliageEditorLibrary not found. "
            "Enable the Foliage editor scripting plugin."
        )
        return

    for mesh_path, instances in foliage_data.items():
        ft = get_or_create_foliage_type(mesh_path)
        if not ft:
            continue

        transforms = [make_transform(inst) for inst in instances]

        try:
            unreal.FoliageEditorLibrary.add_instances(ft, transforms)
            unreal.log(f"[foliage] {len(transforms)} instances added for {mesh_path}")
        except Exception as e:
            unreal.log_warning(f"[foliage] Batch add failed ({e}), trying one-by-one")
            for t in transforms:
                try:
                    unreal.FoliageEditorLibrary.add_instance(ft, t)
                except Exception as e2:
                    unreal.log_error(f"[foliage] add_instance failed: {e2}")
                    break


# ─────────────────────────────────────────
# 3. LANDSCAPE HEIGHTMAP
# ─────────────────────────────────────────

def import_landscape(data):
    if not data:
        unreal.log_warning("[landscape] No landscape data — skipping")
        return None

    heightmap = data.get("heightmap")
    loc       = data["transform"]["location"]
    scl       = data["transform"]["scale"]
    size      = data.get("heightmap_size")

    if not heightmap or not os.path.exists(heightmap):
        unreal.log_error(
            f"[landscape] Heightmap not found: {heightmap}\n"
            "Export manually from Squad SDK: Landscape Mode → Export → R16"
        )
        return None

    quads_per_section = 63
    sections_per_comp = 2

    if size:
        width  = size["width"]
        height = size["height"]
    else:
        file_size    = os.path.getsize(heightmap)
        side         = int((file_size // 2) ** 0.5)
        width        = side
        height       = side
        unreal.log_warning(
            f"[landscape] Size not recorded — inferred {width}x{height} from file size"
        )

    unreal.log(f"[landscape] Importing {width}x{height} from {heightmap}")

    landscape_actor = None

    try:
        subsystem = unreal.get_editor_subsystem(unreal.LandscapeSubsystem)
        if not subsystem:
            raise RuntimeError("LandscapeSubsystem not available")

        params = unreal.LandscapeImportDescriptor()
        params.heightmap_file_path    = heightmap
        params.location               = make_vector(loc)
        params.scale                  = make_vector(scl)
        params.quads_per_section      = quads_per_section
        params.sections_per_component = sections_per_comp

        landscape_actor = subsystem.create_landscape_from_import_descriptor(params)

        if landscape_actor:
            unreal.log("[landscape] Imported successfully via LandscapeSubsystem")
        else:
            raise RuntimeError("create_landscape_from_import_descriptor returned None")

    except Exception as e:
        unreal.log_warning(f"[landscape] LandscapeSubsystem failed: {e}")
        unreal.log(
            "\n--- LANDSCAPE — MANUAL IMPORT REQUIRED ---\n"
            "  1. Toolbar → Landscape mode\n"
            "  2. Import from file\n"
            f"  3. File:               {heightmap}\n"
            f"  4. Location X/Y/Z:    {loc['x']:.1f} / {loc['y']:.1f} / {loc['z']:.1f}\n"
            f"  5. Scale X/Y/Z:       {scl['x']:.4f} / {scl['y']:.4f} / {scl['z']:.4f}\n"
            f"  6. Quads per section: {quads_per_section}\n"
            f"  7. Sections per comp: {sections_per_comp}\n"
            "------------------------------------------"
        )

    return landscape_actor


# ─────────────────────────────────────────
# 4. LANDSCAPE LAYER WEIGHTMAPS
# ─────────────────────────────────────────

def import_landscape_weights(landscape_actor, layers):
    """
    Applies exported weightmap PNGs back onto the UE5 landscape.
    Each layer PNG is imported as a landscape layer file and applied
    using LandscapeEditorLibrary.import_weightmap().

    If the API is unavailable, logs manual instructions per layer.
    """
    if not landscape_actor or not layers:
        return

    for layer in layers:
        name     = layer["name"]
        filepath = layer.get("file")

        if not filepath or not os.path.exists(filepath):
            unreal.log_warning(
                f"[weightmaps] Skipping {name} — file not found: {filepath}"
            )
            continue

        try:
            # Get or create the LayerInfo asset for this layer
            layer_info_path = f"/Game/GeneratedFoliage/LandscapeLayers/{name}_LayerInfo"

            if unreal.EditorAssetLibrary.does_asset_exist(layer_info_path):
                layer_info = unreal.EditorAssetLibrary.load_asset(layer_info_path)
            else:
                layer_info = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
                    f"{name}_LayerInfo",
                    "/Game/GeneratedFoliage/LandscapeLayers",
                    unreal.LandscapeLayerInfoObject,
                    None
                )
                if layer_info:
                    layer_info.set_editor_property("layer_name", name)
                    unreal.EditorAssetLibrary.save_asset(layer_info_path)

            if not layer_info:
                raise RuntimeError(f"Could not create LayerInfo for {name}")

            unreal.LandscapeEditorLibrary.import_weightmap(
                landscape_actor, layer_info, filepath
            )
            unreal.log(f"[weightmaps] Applied {name} from {filepath}")

        except Exception as e:
            unreal.log_warning(
                f"[weightmaps] Could not apply {name} automatically: {e}\n"
                f"  Manual: Landscape Mode → Paint → {name} → Import → {filepath}"
            )


# ─────────────────────────────────────────
# 5. SPLINE ACTORS
# ─────────────────────────────────────────

def spawn_splines(entries):
    """
    Spawns a generic Actor with a SplineComponent for each exported
    spline, restores all control points with their tangents, and
    places it in the correct editor folder.

    These act as reference splines for the artist to use when
    rebuilding roads, rivers, and paths with UE5 tools.
    """
    count = 0
    for entry in entries:
        t = entry["transform"]

        actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
            unreal.Actor,
            make_vector(t["location"]),
            make_rotator(t["rotation"])
        )
        if not actor:
            continue

        actor.set_actor_label(entry.get("label", "SplineActor"))
        set_actor_folder(actor, entry.get("folder", "Splines"))

        for spline_data in entry.get("splines", []):
            comp = None
            
            # Try to add component via EditorLevelLibrary
            if hasattr(unreal.EditorLevelLibrary, "add_component"):
                try:
                    comp = unreal.EditorLevelLibrary.add_component(
                        actor,
                        unreal.SplineComponent,
                        unreal.Transform()
                    )
                except Exception as e:
                    unreal.log_warning(f"[splines] add_component failed: {e}")
            
            # If that failed, skip this spline
            if not comp:
                unreal.log_warning(
                    f"[splines] Could not create SplineComponent for {entry.get('label', 'Spline')} "
                    "— try enabling Spline editor scripting plugin"
                )
                continue

            points = spline_data.get("points", [])

            # Clear default points then add ours
            comp.clear_spline_points(False)

            for pt in points:
                pos = pt["position"]
                comp.add_spline_point(
                    make_vector(pos),
                    unreal.SplineCoordinateSpace.WORLD,
                    False  # don't update spline yet
                )

            # Set tangents after all points exist
            for i, pt in enumerate(points):
                comp.set_tangents_at_spline_point(
                    i,
                    make_vector(pt["arrive_tangent"]),
                    make_vector(pt["leave_tangent"]),
                    unreal.SplineCoordinateSpace.WORLD,
                    False
                )

            comp.set_closed_loop(spline_data.get("closed", False), False)
            comp.update_spline()

        count += 1

    unreal.log(f"[splines] {count} spline actors spawned")


# ─────────────────────────────────────────
# 6. DECAL ACTORS
# ─────────────────────────────────────────

def spawn_decals(entries):
    count = 0
    for entry in entries:
        t   = entry["transform"]
        loc = t["location"]
        rot = t["rotation"]
        scl = t["scale"]

        actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
            unreal.DecalActor,
            make_vector(loc),
            make_rotator(rot)
        )
        if not actor:
            continue

        actor.set_actor_scale3d(make_vector(scl))
        actor.set_actor_label(entry.get("label", "Decal"))
        set_actor_folder(actor, entry.get("folder", "Decals"))

        mat_path = entry.get("material", "")
        if mat_path:
            mat = unreal.EditorAssetLibrary.load_asset(mat_path)
            if mat:
                comp = actor.get_component_by_class(unreal.DecalComponent)
                if comp:
                    comp.set_decal_material(mat)

                    sz = entry.get("size", {})
                    if sz:
                        try:
                            comp.set_editor_property(
                                "decal_size",
                                unreal.Vector(sz["x"], sz["y"], sz["z"])
                            )
                        except Exception:
                            pass

        count += 1

    unreal.log(f"[decals] {count} decal actors spawned")


# ─────────────────────────────────────────
# 7. VOLUMES
# ─────────────────────────────────────────

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

VOLUME_CLASS_MAP = {
    name: getattr(unreal, name)
    for name in _VOLUME_CLASS_NAMES
    if hasattr(unreal, name)
}


def spawn_volumes(entries):
    """
    Spawns volumes by class name, restores transform, and applies
    a box brush scaled to match the original bounding extents.

    PostProcessVolume settings (exposure, bloom etc.) are also
    restored as a reference starting point.
    """
    count = 0
    for entry in entries:
        class_name = entry.get("class", "")
        ue_class   = VOLUME_CLASS_MAP.get(class_name)

        if not ue_class:
            unreal.log_warning(f"[volumes] Unknown volume class: {class_name} — skipping")
            continue

        t   = entry["transform"]
        loc = t["location"]
        rot = t["rotation"]

        actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
            ue_class,
            make_vector(loc),
            make_rotator(rot)
        )
        if not actor:
            continue

        actor.set_actor_label(entry.get("label", class_name))
        set_actor_folder(actor, entry.get("folder", "Volumes"))

        # Set the brush extent to match original size
        ext = entry.get("bounds_extent", {})
        if ext and (ext.get("x") or ext.get("y") or ext.get("z")):
            try:
                # Try to set brush component scale
                brush = actor.get_component_by_class(unreal.BrushComponent)
                if brush:
                    brush.set_relative_scale3d(
                        unreal.Vector(
                            max(0.1, ext["x"] / 100.0),
                            max(0.1, ext["y"] / 100.0),
                            max(0.1, ext["z"] / 100.0)
                        )
                    )
                else:
                    # Fallback to actor scale if no brush found
                    actor.set_actor_scale3d(
                        unreal.Vector(
                            max(0.1, ext["x"] / 100.0),
                            max(0.1, ext["y"] / 100.0),
                            max(0.1, ext["z"] / 100.0)
                        )
                    )
            except Exception as e:
                unreal.log_warning(f"[volumes] Could not set extent scale: {e}")

        # Restore PostProcessVolume settings
        pp = entry.get("post_process")
        if pp and isinstance(actor, unreal.PostProcessVolume):
            try:
                settings = actor.get_editor_property("settings")
                if pp.get("exposure_compensation") is not None:
                    settings.set_editor_property(
                        "auto_exposure_bias", pp["exposure_compensation"]
                    )
                if pp.get("bloom_intensity") is not None:
                    settings.set_editor_property(
                        "bloom_intensity", pp["bloom_intensity"]
                    )
                actor.set_editor_property("settings", settings)
                if pp.get("infinite_extent") is not None:
                    actor.set_editor_property("infinite_extent", pp["infinite_extent"])
                if pp.get("priority") is not None:
                    actor.set_editor_property("priority", pp["priority"])
            except Exception as e:
                unreal.log_warning(f"[volumes] Could not restore PP settings: {e}")

        count += 1

    unreal.log(f"[volumes] {count} volumes spawned")


# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────

def main():
    if not os.path.exists(INPUT_JSON):
        unreal.log_error(f"Input file not found: {INPUT_JSON}")
        return

    with open(INPUT_JSON, "r") as f:
        data = json.load(f)

    # Ensure asset directories exist
    for path in [FOLIAGE_ASSET_PATH, "/Game/GeneratedFoliage/LandscapeLayers"]:
        if not unreal.EditorAssetLibrary.does_directory_exist(path):
            unreal.EditorAssetLibrary.make_directory(path)

    unreal.log("--- Starting UE5 map import ---")

    unreal.log(f"Spawning {len(data.get('static_meshes', []))} static mesh actors...")
    spawn_static_meshes(data.get("static_meshes", []))

    unreal.log("Spawning foliage...")
    spawn_foliage(data.get("foliage", {}))

    unreal.log("Importing landscape...")
    landscape_actor = import_landscape(data.get("landscape"))

    unreal.log("Applying landscape weightmaps...")
    import_landscape_weights(
        landscape_actor,
        (data.get("landscape") or {}).get("layers", [])
    )

    unreal.log(f"Spawning {len(data.get('splines', []))} spline actors...")
    spawn_splines(data.get("splines", []))

    unreal.log(f"Spawning {len(data.get('decals', []))} decal actors...")
    spawn_decals(data.get("decals", []))

    unreal.log(f"Spawning {len(data.get('volumes', []))} volumes...")
    spawn_volumes(data.get("volumes", []))

    unreal.log("--- Import complete ---")


main()
