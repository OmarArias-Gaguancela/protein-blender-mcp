"""Command handlers that run inside Blender on the main thread.

Every public handler takes keyword arguments decoded from JSON and returns a
JSON-serialisable dict. They are registered in ``COMMANDS`` at the bottom.
"""

from __future__ import annotations

import contextlib
import importlib
import io
import os
import sys
import tempfile
import traceback
from pathlib import Path

import bpy

# --------------------------------------------------------------------------
# Molecular Nodes discovery
# --------------------------------------------------------------------------

_MN = None


def mn():
    """Return the Molecular Nodes package, wherever Blender installed it.

    As a Blender extension it lives at ``bl_ext.<repo>.molecularnodes``; as a
    legacy add-on or pip install it is plain ``molecularnodes``.
    """
    global _MN
    if _MN is not None:
        return _MN
    candidates = [
        name
        for name in sys.modules
        if name == "molecularnodes" or name.endswith(".molecularnodes")
    ]
    candidates += ["bl_ext.blender_org.molecularnodes", "molecularnodes"]
    for name in candidates:
        try:
            _MN = importlib.import_module(name)
        except ImportError:
            continue
        # make sure MN's scene properties (e.g. Scene.MNSession) exist; this is a
        # no-op when Blender already enabled the extension
        if not hasattr(bpy.types.Scene, "MNSession"):
            _MN.register()
        return _MN
    raise RuntimeError(
        "Molecular Nodes is not installed or not enabled. Install it from "
        "Edit > Preferences > Get Extensions and enable it."
    )


def geo():
    return importlib.import_module(mn().__name__ + ".nodes.geometry")


def session():
    return mn().session.get_session(bpy.context)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

NAMED_COLORS = {
    "white": "#ffffff", "black": "#000000", "grey": "#808080", "gray": "#808080",
    "lightgrey": "#d3d3d3", "lightgray": "#d3d3d3", "darkgrey": "#404040",
    "darkgray": "#404040", "red": "#e53935", "darkred": "#8b0000",
    "crimson": "#dc143c", "salmon": "#fa8072", "pink": "#ff8fb1",
    "hotpink": "#ff69b4", "magenta": "#ff00ff", "purple": "#8e44ad",
    "violet": "#b57edc", "lavender": "#c3b1e1", "indigo": "#4b0082",
    "blue": "#1e88e5", "navy": "#1a237e", "darkblue": "#0d2c8a",
    "skyblue": "#87ceeb", "lightblue": "#90caf9", "cornflowerblue": "#6495ed",
    "cyan": "#00bcd4", "teal": "#00897b", "turquoise": "#40e0d0",
    "green": "#43a047", "darkgreen": "#1b5e20", "lime": "#a4e000",
    "lightgreen": "#a5d6a7", "olive": "#808000", "mint": "#98ff98",
    "yellow": "#fdd835", "gold": "#ffc107", "orange": "#fb8c00",
    "darkorange": "#e65100", "coral": "#ff7f50", "peach": "#ffcba4",
    "brown": "#795548", "tan": "#d2b48c", "beige": "#f5f5dc", "ivory": "#fffff0",
    "cream": "#fffdd0", "silver": "#c0c0c0",
}

COLOR_SCHEMES = {
    "element": "Element colors (O red, N blue, S yellow) with carbons tinted per chain",
    "chain": "A distinct color for every chain",
    "rainbow": "Rainbow along each chain, N- to C-terminus",
    "secondary_structure": "Helix, sheet and loop each get their own color",
    "residue_type": "Color by amino acid / nucleotide type",
    "b_factor": "Map B-factor (flexibility) onto a blue-white-red gradient",
    "plddt": "AlphaFold pLDDT confidence colors",
    "goodsell": "Goodsell style: carbons darkened, flat illustrative look",
}

MATERIALS = {
    "default": "Default",
    "ambient_occlusion": "AmbientOcclusion",
    "flat": "Flat",
    "squishy": "Squishy",
    "transparent": "Transparent",
}

STYLES = ["cartoon", "ribbon", "surface", "sticks", "spheres", "ball_and_stick"]


def _srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def parse_rgba(color) -> tuple[float, float, float, float]:
    """Turn a color name, hex string or RGB(A) list into linear RGBA."""
    if isinstance(color, (list, tuple)):
        vals = [float(v) for v in color]
        if any(v > 1 for v in vals):  # 0-255 values
            vals = [v / 255 for v in vals]
        rgb = [_srgb_to_linear(v) for v in vals[:3]]
        alpha = vals[3] if len(vals) > 3 else 1.0
        return (*rgb, alpha)
    text = str(color).strip().lower().replace(" ", "").replace("_", "")
    text = NAMED_COLORS.get(text, text)
    if not text.startswith("#"):
        text = "#" + text
    hexval = text[1:]
    if len(hexval) == 3:
        hexval = "".join(ch * 2 for ch in hexval)
    if len(hexval) not in (6, 8):
        raise ValueError(
            f"Unknown color '{color}'. Use a name like 'red', a hex code like "
            f"'#ff8800', an RGB list, or a scheme: {sorted(COLOR_SCHEMES)}"
        )
    vals = [int(hexval[i : i + 2], 16) / 255 for i in range(0, len(hexval), 2)]
    rgb = [_srgb_to_linear(v) for v in vals[:3]]
    return (*rgb, vals[3] if len(vals) > 3 else 1.0)


def color_input(color):
    """Translate a user-facing color into what ``Molecule.add_style`` accepts."""
    if color is None:
        return None
    if isinstance(color, str):
        key = color.strip().lower().replace(" ", "_").replace("-", "_")
        g = geo()
        if key in ("element", "common", "default", "cpk", "atom"):
            return "common"
        if key in ("plddt", "confidence", "alphafold"):
            return "plddt"
        if key in ("chain", "chains", "by_chain"):
            return lambda: g.RandomColor(id=g.ChainID(), color_seed=3)
        if key in ("rainbow", "n_to_c", "spectrum"):
            return lambda: g.ColorRainbow(factor="Chain")
        if key in ("secondary_structure", "ss", "dssp", "structure"):
            return lambda: g.ColorSecondaryStructure()
        if key in ("residue_type", "res_name", "residue_name", "amino_acid"):
            return lambda: g.ColorResName()
        if key in ("b_factor", "bfactor", "flexibility", "temperature"):
            return lambda: g.ColorAttributeMap(name="b_factor", min=0.0, max=100.0)
        if key == "goodsell":
            return lambda: g.ColorGoodsell()
    return parse_rgba(color)


def material_input(material):
    if material is None:
        return mn().material.Default()
    key = str(material).strip().lower().replace(" ", "_").replace("-", "_")
    if key not in MATERIALS:
        raise ValueError(f"Unknown material '{material}'. Options: {sorted(MATERIALS)}")
    return getattr(mn().material, MATERIALS[key])()


def get_molecule(name: str | None = None):
    """Find a Molecular Nodes molecule by object name (or the active/latest one)."""
    sess = session()
    sess.prune()
    mols = list(sess.molecules.values())
    if not mols:
        raise ValueError("No molecules in the scene. Fetch or load a structure first.")
    if name:
        for mol in mols:
            if mol.object.name.lower() == name.lower():
                return mol
        for mol in mols:
            if mol.object.name.lower().startswith(name.lower()):
                return mol
        raise ValueError(
            f"No molecule named '{name}'. Available: {[m.object.name for m in mols]}"
        )
    active = bpy.context.view_layer.objects.active
    if active is not None:
        mol = sess.match(active)
        if mol is not None and mol in mols:
            return mol
    return mols[-1]


def _style_nodes(mol):
    return [
        node
        for node in mol.node_group.nodes
        if node.bl_idname == "GeometryNodeGroup"
        and node.node_tree is not None
        and node.node_tree.name.startswith("Style")
    ]


def _describe_molecule(mol) -> dict:
    u = mol.universe
    atoms = u.atoms
    chains = sorted({str(c) for c in atoms.chainIDs}) if hasattr(atoms, "chainIDs") else []
    info = {
        "name": mol.object.name,
        "atoms": int(atoms.n_atoms),
        "residues": int(u.residues.n_residues),
        "chains": chains,
        "styles": [
            {
                "index": i,
                "style": node.node_tree.name,
                "label": node.label or None,
            }
            for i, node in enumerate(_style_nodes(mol))
        ],
    }
    try:
        het = u.select_atoms("not protein and not nucleic and not water")
        info["ligands"] = sorted({str(r) for r in het.residues.resnames})
    except Exception:
        info["ligands"] = []
    try:
        info["has_water"] = bool(u.select_atoms("water").n_atoms)
    except Exception:
        pass
    return info


def _canvas():
    # template=None binds to the current scene without loading a preset scene
    return mn().Canvas(template=None)


def _ensure_camera():
    scene = bpy.context.scene
    if scene.camera is None:
        cam_data = bpy.data.cameras.new("Camera")
        cam = bpy.data.objects.new("Camera", cam_data)
        scene.collection.objects.link(cam)
        scene.camera = cam
    return scene.camera


# --------------------------------------------------------------------------
# Command handlers
# --------------------------------------------------------------------------


def ping() -> dict:
    return {"ok": True, "blender": bpy.app.version_string, "molecular_nodes": mn().__name__}


def get_scene_info() -> dict:
    sess = session()
    sess.prune()
    scene = bpy.context.scene
    return {
        "molecules": [_describe_molecule(m) for m in sess.molecules.values()],
        "render_engine": scene.render.engine,
        "resolution": [scene.render.resolution_x, scene.render.resolution_y],
        "camera": scene.camera.name if scene.camera else None,
        "available_styles": STYLES,
        "available_color_schemes": COLOR_SCHEMES,
        "available_materials": sorted(MATERIALS),
    }


def _apply_initial_style(mol, style, color, material):
    if style and style != "none":
        mol.add_style(
            style=style, color=color_input(color), material=material_input(material)
        )


def fetch_structure(
    code: str,
    style: str | None = "cartoon",
    color: str | None = "chain",
    material: str | None = None,
    database: str = "rcsb",
    frame_camera: bool = True,
) -> dict:
    mol = mn().Molecule.fetch(code.strip(), database=database)
    _apply_initial_style(mol, style, color, material)
    if frame_camera:
        _frame(mol, None, "front")
    return {"loaded": _describe_molecule(mol)}


def load_file(
    path: str,
    style: str | None = "cartoon",
    color: str | None = "chain",
    material: str | None = None,
    frame_camera: bool = True,
) -> dict:
    file_path = Path(os.path.expanduser(path))
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    mol = mn().Molecule.load(str(file_path))
    _apply_initial_style(mol, style, color, material)
    if frame_camera:
        _frame(mol, None, "front")
    return {"loaded": _describe_molecule(mol)}


def add_style(
    style: str = "cartoon",
    selection: str | None = None,
    color=None,
    material: str | None = None,
    molecule: str | None = None,
    label: str | None = None,
    options: dict | None = None,
) -> dict:
    mol = get_molecule(molecule)
    if style not in STYLES:
        raise ValueError(f"Unknown style '{style}'. Options: {STYLES}")
    if selection:
        n = mol.universe.select_atoms(selection).n_atoms  # validates the phrase
        if n == 0:
            raise ValueError(f"Selection '{selection}' matched 0 atoms.")
    mol.add_style(
        style=style,
        selection=selection or None,
        color=color_input(color),
        material=material_input(material),
        name=label,
        **(options or {}),
    )
    return {"molecule": _describe_molecule(mol)}


def clear_styles(molecule: str | None = None) -> dict:
    mol = get_molecule(molecule)
    with mol.tree.reset():
        pass
    return {"molecule": _describe_molecule(mol)}


def remove_style(index: int, molecule: str | None = None) -> dict:
    mol = get_molecule(molecule)
    nodes = _style_nodes(mol)
    if not 0 <= index < len(nodes):
        raise ValueError(f"Style index {index} out of range (0..{len(nodes) - 1}).")
    target = nodes[index]
    tree = mol.node_group
    # also drop a Set Color node feeding only this style
    for link in list(target.inputs[0].links) if target.inputs else []:
        upstream = link.from_node
        if upstream.bl_idname == "GeometryNodeSetColor" or (
            getattr(upstream, "node_tree", None) is not None
            and "Color" in upstream.node_tree.name
            and len(upstream.outputs[0].links) == 1
        ):
            tree.nodes.remove(upstream)
    tree.nodes.remove(target)
    return {"molecule": _describe_molecule(mol)}


def _frame(mol, selection, viewpoint):
    _ensure_camera()
    canvas = _canvas()
    # orient on the whole molecule first, then (keeping that direction) move in
    # to fit the selection - passing a viewpoint with raw points is unreliable
    canvas.look_at(mol, viewpoint=viewpoint or "default")
    if selection:
        if mol.universe.select_atoms(selection).n_atoms == 0:
            raise ValueError(f"Selection '{selection}' matched 0 atoms.")
        canvas.look_at(mol.get_view(selection))


def frame_camera(
    molecule: str | None = None,
    selection: str | None = None,
    viewpoint: str = "front",
) -> dict:
    mol = get_molecule(molecule)
    _frame(mol, selection, viewpoint)
    return {"camera": bpy.context.scene.camera.name, "viewpoint": viewpoint}


def set_background(
    color="white",
    transparent: bool = False,
    lighting_strength: float = 1.0,
    exact_colors: bool = True,
) -> dict:
    """Set what the camera sees behind the molecule.

    The world also lights the scene, so the camera background and the lighting
    are split with a Light Path node: a black background no longer means a
    black, unlit molecule.
    """
    scene = bpy.context.scene
    world = bpy.data.worlds.get("ProteinMCP World") or bpy.data.worlds.new(
        "ProteinMCP World"
    )
    scene.world = world
    world.use_nodes = True
    tree = world.node_tree
    tree.nodes.clear()
    out = tree.nodes.new("ShaderNodeOutputWorld")
    light = tree.nodes.new("ShaderNodeBackground")
    light.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
    light.inputs["Strength"].default_value = float(lighting_strength)
    seen = tree.nodes.new("ShaderNodeBackground")
    seen.inputs["Color"].default_value = parse_rgba(color)
    seen.inputs["Strength"].default_value = 1.0
    path = tree.nodes.new("ShaderNodeLightPath")
    mix = tree.nodes.new("ShaderNodeMixShader")
    tree.links.new(path.outputs["Is Camera Ray"], mix.inputs["Fac"])
    tree.links.new(light.outputs[0], mix.inputs[1])
    tree.links.new(seen.outputs[0], mix.inputs[2])
    tree.links.new(mix.outputs[0], out.inputs[0])
    scene.render.film_transparent = bool(transparent)
    if exact_colors:
        # AgX/Filmic tone mapping turns white into grey and dulls picked colors
        scene.view_settings.view_transform = "Standard"
    return {
        "background": color,
        "transparent": transparent,
        "view_transform": scene.view_settings.view_transform,
    }


def set_render_settings(
    engine: str | None = None,
    resolution: list[int] | None = None,
    samples: int | None = None,
) -> dict:
    canvas = _canvas()
    if engine:
        key = engine.strip().upper()
        canvas.engine = "CYCLES" if key.startswith("CYC") else "EEVEE"
    if resolution:
        canvas.resolution = (int(resolution[0]), int(resolution[1]))
    if samples:
        canvas.samples = int(samples)
    scene = bpy.context.scene
    return {
        "engine": scene.render.engine,
        "resolution": [scene.render.resolution_x, scene.render.resolution_y],
    }


def render_image(path: str | None = None, resolution_percentage: int = 100) -> dict:
    scene = bpy.context.scene
    if scene.camera is None:
        mols = list(session().molecules.values())
        if mols:
            _frame(mols[-1], None, "front")
        else:
            _ensure_camera()
    if not path:
        path = os.path.join(tempfile.gettempdir(), "protein_blender_mcp_render.png")
    path = str(Path(os.path.expanduser(path)).resolve())
    old_path = scene.render.filepath
    old_pct = scene.render.resolution_percentage
    old_fmt = scene.render.image_settings.file_format
    try:
        scene.render.filepath = path
        scene.render.resolution_percentage = int(resolution_percentage)
        scene.render.image_settings.file_format = "PNG"
        bpy.ops.render.render(write_still=True)
    finally:
        scene.render.filepath = old_path
        scene.render.resolution_percentage = old_pct
        scene.render.image_settings.file_format = old_fmt
    return {"path": path}


def delete_molecule(molecule: str) -> dict:
    mol = get_molecule(molecule)
    name = mol.object.name
    session().remove(mol.uuid)
    return {"deleted": name}


def save_blend(path: str) -> dict:
    path = str(Path(os.path.expanduser(path)).resolve())
    bpy.ops.wm.save_as_mainfile(filepath=path, copy=True)
    return {"saved": path}


def execute_python(code: str) -> dict:
    """Run arbitrary Python in Blender. Escape hatch for anything not covered."""
    namespace = {
        "bpy": bpy,
        "mn": mn(),
        "mg": geo(),
        "get_molecule": get_molecule,
        "parse_rgba": parse_rgba,
    }
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        exec(code, namespace)
    return {"stdout": out.getvalue(), "result": repr(namespace.get("result"))}


COMMANDS = {
    "ping": ping,
    "get_scene_info": get_scene_info,
    "fetch_structure": fetch_structure,
    "load_file": load_file,
    "add_style": add_style,
    "clear_styles": clear_styles,
    "remove_style": remove_style,
    "frame_camera": frame_camera,
    "set_background": set_background,
    "set_render_settings": set_render_settings,
    "render_image": render_image,
    "delete_molecule": delete_molecule,
    "save_blend": save_blend,
    "execute_python": execute_python,
}


def dispatch(command: str, params: dict | None) -> dict:
    handler = COMMANDS.get(command)
    if handler is None:
        return {"status": "error", "message": f"Unknown command '{command}'"}
    try:
        return {"status": "ok", "result": handler(**(params or {}))}
    except Exception as exc:  # report every failure back to the MCP client
        return {
            "status": "error",
            "message": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(limit=6),
        }
