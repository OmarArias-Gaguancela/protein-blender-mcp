"""MCP server that lets an AI assistant style protein structures in Blender.

It talks to the Protein Blender MCP add-on running inside Blender over a local
TCP socket (default port 9877, override with ``PROTEIN_BLENDER_PORT``).
"""

from __future__ import annotations

import json
import os
import socket
from typing import Any, Literal

try:  # mcp >= 2.0
    from mcp.server.mcpserver import Image
    from mcp.server.mcpserver import MCPServer as FastMCP
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP, Image
    from mcp.server.fastmcp.exceptions import ToolError

HOST = os.environ.get("PROTEIN_BLENDER_HOST", "127.0.0.1")
PORT = int(os.environ.get("PROTEIN_BLENDER_PORT", "9877"))

Style = Literal["cartoon", "ribbon", "surface", "sticks", "spheres", "ball_and_stick"]
Material = Literal["default", "ambient_occlusion", "flat", "squishy", "transparent"]
Viewpoint = Literal["default", "front", "back", "top", "bottom", "left", "right"]

SELECTION_HELP = """
Selections use MDAnalysis selection syntax, for example:
  "chainID A"                       one chain (also "segid A")
  "chainID A B"                     several chains
  "protein"  /  "nucleic"           all protein / DNA-RNA atoms
  "resid 10:50"                     residue range
  "resname HEM"                     a ligand or residue type by name
  "not protein and not nucleic and not water"   ligands and other het groups
  "protein and around 5 resname ATP"            binding pocket within 5 A
  "backbone"  /  "name CA"          backbone atoms / alpha carbons
  "resname LYS ARG"  /  "resname ASP GLU"       basic / acidic residues
Combine with and / or / not and parentheses.
"""

COLOR_HELP = """
Color can be a scheme or a single color.
Schemes: "element", "chain", "rainbow" (N->C terminus), "secondary_structure",
"residue_type", "b_factor", "plddt", "goodsell".
Single colors: a name ("red", "skyblue", "gold"...), a hex code ("#ff8800") or an
RGB list ([255, 136, 0]).
"""

mcp = FastMCP(
    "protein-blender",
    instructions=(
        "Tools for styling protein and nucleic-acid 3D structures in Blender with "
        "Molecular Nodes. Typical flow: fetch_structure or load_file -> "
        "get_scene_info (see chains and ligands) -> clear_styles / add_style to build "
        "the look -> set_background, frame_camera -> render_image to check the "
        "result and iterate. Styles stack: each add_style adds another layer, so "
        "call clear_styles first when the user wants to restyle from scratch. Pick "
        "selections that match the user's words, e.g. 'the ligand' -> "
        "\"not protein and not nucleic and not water\"."
    ),
)


class BlenderConnectionError(ToolError):
    pass


def send_command(command: str, params: dict[str, Any] | None = None) -> Any:
    """Send one command to the Blender add-on and return its result."""
    payload = json.dumps({"command": command, "params": params or {}}).encode() + b"\n"
    try:
        with socket.create_connection((HOST, PORT), timeout=10) as sock:
            sock.settimeout(620)
            sock.sendall(payload)
            buffer = b""
            while b"\n" not in buffer:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buffer += chunk
    except OSError as exc:
        raise BlenderConnectionError(
            f"Could not reach Blender on {HOST}:{PORT} ({exc}). Open Blender, then in "
            "the 3D viewport press N, open the 'Protein MCP' tab and click "
            "'Start MCP Bridge'."
        ) from exc
    if not buffer:
        raise BlenderConnectionError("Blender closed the connection without replying.")
    response = json.loads(buffer.split(b"\n", 1)[0])
    if response.get("status") != "ok":
        raise ToolError(response.get("message", "Unknown error from Blender"))
    return response.get("result")


def _clean(params: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in params.items() if v is not None}


@mcp.tool()
def get_scene_info() -> dict:
    """List the molecules in the scene with their chains, ligands, residue counts
    and current style layers, plus render settings and the available styles,
    color schemes and materials. Call this before styling to learn chain IDs and
    ligand names."""
    return send_command("get_scene_info")


@mcp.tool()
def fetch_structure(
    pdb_id: str,
    style: Style | Literal["none"] = "cartoon",
    color: str = "chain",
    material: Material | None = None,
    database: Literal["rcsb", "alphafold"] = "rcsb",
) -> dict:
    """Download a structure by ID and add it to the scene with an initial style.

    pdb_id: a PDB code like "4HHB", or a UniProt accession when database is
    "alphafold". Use style="none" to load without any style and build it up with
    add_style.
    """
    return send_command(
        "fetch_structure",
        _clean(
            {
                "code": pdb_id,
                "style": style,
                "color": color,
                "material": material,
                "database": database,
            }
        ),
    )


@mcp.tool()
def load_file(
    path: str,
    style: Style | Literal["none"] = "cartoon",
    color: str = "chain",
    material: Material | None = None,
) -> dict:
    """Load a local structure file (.pdb, .cif, .bcif, .sdf, .mol) into the scene."""
    return send_command(
        "load_file",
        _clean({"path": path, "style": style, "color": color, "material": material}),
    )


ADD_STYLE_DOC = (
    """Add a style layer to a molecule, optionally limited to a selection.

Layers stack, so "cartoon for the protein plus sticks for the ligand" is two
calls. molecule is the object name from get_scene_info (default: the active
or most recently loaded one). label names the layer for later removal.

options passes extra settings straight to the Molecular Nodes style node, e.g.
cartoon: {"quality": 4, "helix_shape": "Cylinder", "loop_radius": 0.3,
"sheet_arrows": "Flat"}; surface: {"quality": 4, "scale": 1.5,
"separate_by": "chain_id"}; spheres/sticks: {"scale": 0.8}.
"""
    + SELECTION_HELP
    + COLOR_HELP
)


@mcp.tool(description=ADD_STYLE_DOC)
def add_style(
    style: Style,
    selection: str | None = None,
    color: str | list[float] | None = None,
    material: Material | None = None,
    molecule: str | None = None,
    label: str | None = None,
    options: dict[str, Any] | None = None,
) -> dict:
    return send_command(
        "add_style",
        _clean(
            {
                "style": style,
                "selection": selection,
                "color": color,
                "material": material,
                "molecule": molecule,
                "label": label,
                "options": options,
            }
        ),
    )


@mcp.tool()
def clear_styles(molecule: str | None = None) -> dict:
    """Remove every style layer from a molecule so it can be restyled from scratch."""
    return send_command("clear_styles", _clean({"molecule": molecule}))


@mcp.tool()
def remove_style(index: int, molecule: str | None = None) -> dict:
    """Remove one style layer by its index (see get_scene_info)."""
    return send_command("remove_style", _clean({"index": index, "molecule": molecule}))


@mcp.tool()
def frame_camera(
    molecule: str | None = None,
    selection: str | None = None,
    viewpoint: Viewpoint = "front",
) -> dict:
    """Point the scene camera at a molecule, or zoom in on a selection such as a
    binding site, from the given viewpoint."""
    return send_command(
        "frame_camera",
        _clean({"molecule": molecule, "selection": selection, "viewpoint": viewpoint}),
    )


@mcp.tool()
def set_background(
    color: str = "white",
    transparent: bool = False,
    lighting_strength: float = 1.0,
) -> dict:
    """Set the background color the camera sees (name or hex), or make it
    transparent for figures placed on another background. Lighting is kept
    separate, so dark backgrounds still light the molecule; raise
    lighting_strength (e.g. 1.5) for a brighter scene."""
    return send_command(
        "set_background",
        {"color": color, "transparent": transparent, "lighting_strength": lighting_strength},
    )


@mcp.tool()
def set_render_settings(
    engine: Literal["EEVEE", "CYCLES"] | None = None,
    width: int | None = None,
    height: int | None = None,
    samples: int | None = None,
) -> dict:
    """Choose the render engine (EEVEE is fast, CYCLES is photoreal), output size in
    pixels and sample count."""
    resolution = [width, height] if width and height else None
    return send_command(
        "set_render_settings",
        _clean({"engine": engine, "resolution": resolution, "samples": samples}),
    )


@mcp.tool()
def render_image(path: str | None = None, preview: bool = True) -> list:
    """Render the scene from the camera and return the image so you can check the
    styling. preview=True renders at 50% size for speed; set preview=False and give
    a path for the final figure."""
    result = send_command(
        "render_image",
        _clean({"path": path, "resolution_percentage": 50 if preview else 100}),
    )
    out_path = result["path"]
    with open(out_path, "rb") as fh:
        data = fh.read()
    return [f"Saved render to {out_path}", Image(data=data, format="png")]


@mcp.tool()
def delete_molecule(molecule: str) -> dict:
    """Remove a molecule from the scene."""
    return send_command("delete_molecule", {"molecule": molecule})


@mcp.tool()
def save_blend(path: str) -> dict:
    """Save a copy of the current scene as a .blend file."""
    return send_command("save_blend", {"path": path})


@mcp.tool()
def execute_blender_python(code: str) -> dict:
    """Run Python inside Blender for anything the other tools do not cover (custom
    lighting, node tweaks, animation). Available names: bpy, mn (Molecular Nodes),
    mg (Molecular Nodes geometry nodes), get_molecule(name). Assign to `result` or
    print() to return output. Prefer the dedicated tools when they fit."""
    return send_command("execute_python", {"code": code})


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
