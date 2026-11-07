# protein-blender-mcp

Style protein 3D structures in Blender by describing what you want in plain English.

> "Fetch 4HHB, show the protein as a cartoon colored by chain, the hemes as sticks, put it on a white background and render it."

`protein-blender-mcp` is a [Model Context Protocol](https://modelcontextprotocol.io) server that connects an AI assistant such as Claude to Blender. It uses [Molecular Nodes](https://github.com/BradyAJohnston/MolecularNodes) to import and draw structures. The assistant turns your words into tool calls like `add_style(style="sticks", selection="resname HEM", color="element")`. It then renders a preview to check the result, so you can keep refining in conversation.

```
You ──► Claude ──► protein-blender-mcp (MCP server) ──TCP:9877──► Blender add-on ──► Molecular Nodes
```

## What you can ask for

- **Load:** fetch from the PDB (`4HHB`) or AlphaFold DB (UniProt ID), or open a local `.pdb` / `.cif` / `.bcif` / `.sdf` file
- **Styles:** cartoon, ribbon, surface, sticks, spheres, ball-and-stick, layered on any selection
- **Selections:** chains, residue ranges, ligands, binding pockets ("residues within 5 Å of ATP"), backbone, residue types
- **Colors:** by element, chain, rainbow (N→C), secondary structure, residue type, B-factor, AlphaFold pLDDT, Goodsell style, or any named / hex color
- **Materials:** default, ambient occlusion, flat, squishy, transparent
- **Scene:** background color or transparency, camera framing from front/back/top/…, EEVEE or Cycles, resolution
- **Output:** preview renders returned to the assistant, final PNG renders, saved `.blend` files
- **Escape hatch:** run arbitrary Blender Python for anything else (lighting, animation, node tweaks)

## Requirements

- [Blender](https://www.blender.org/download/) 4.2 or newer (developed on 5.2)
- [Molecular Nodes](https://extensions.blender.org/add-ons/molecularnodes/) installed and enabled in Blender
- [uv](https://docs.astral.sh/uv/getting-started/installation/) (recommended), or Python 3.10+
- An MCP client, such as Claude Desktop, Claude Code or Cursor

## Installation

### 1. Install the Blender add-on

1. Download this repository and zip the `addon/protein_blender_mcp` folder, or run `python scripts/build_addon.py`, which writes `dist/protein_blender_mcp.zip`.
2. In Blender, open **Edit → Preferences → Get Extensions**, click the **⌄** menu in the top right, and choose **Install from Disk…**. Select the zip.
3. In the 3D viewport, press **N**, open the **Protein MCP** tab, and click **Start MCP Bridge**.

### 2. Register the MCP server with your client

**Claude Code**

```bash
claude mcp add protein-blender -- uvx --from git+https://github.com/OmarArias-Gaguancela/protein-blender-mcp protein-blender-mcp
```

**Claude Desktop** (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "protein-blender": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/OmarArias-Gaguancela/protein-blender-mcp", "protein-blender-mcp"]
    }
  }
}
```

**From a local clone**

```bash
pip install -e .
```

Then use `protein-blender-mcp` as the command.

Set `PROTEIN_BLENDER_PORT` if you changed the port in the Blender panel.

## Example prompts

- "Load 1EMA (GFP) as a cartoon colored rainbow from N to C terminus, with the chromophore as ball-and-stick."
- "Show 6VXX as a surface colored by chain, with a flat material on a black background."
- "Fetch AlphaFold model P69905 and color it by pLDDT confidence."
- "Zoom in on the binding pocket of 3HTB: residues within 5 Å of the ligand as sticks, everything else as a transparent cartoon."
- "Make the helices cylinders and the sheets flat, then render a 1920×1080 image with Cycles to `~/Desktop/figure.png`."

## Tools

| Tool | What it does |
|---|---|
| `get_scene_info` | Molecules, chains, ligands, style layers, render settings |
| `fetch_structure` | Download from RCSB or AlphaFold DB with an initial style |
| `load_file` | Load a local structure file |
| `add_style` | Add a style layer to a selection with a color and material |
| `clear_styles` / `remove_style` | Remove style layers |
| `frame_camera` | Point the camera at a molecule or selection |
| `set_background` | Background color or transparency |
| `set_render_settings` | Engine, resolution, samples |
| `render_image` | Render and return the image |
| `delete_molecule`, `save_blend` | Scene housekeeping |
| `execute_blender_python` | Run custom Python inside Blender |

## Security note

The Blender add-on listens only on `127.0.0.1`. The `execute_blender_python` tool runs whatever code the assistant sends, so only connect clients you trust. Stop the bridge from the panel when you're not using it.

## Troubleshooting

- **"Could not reach Blender"**: make sure Blender is open and the panel says *Running on port 9877*.
- **"Molecular Nodes is not installed"**: install it from Get Extensions and enable it.
- **Nothing visible after styling**: ask the assistant to call `get_scene_info` and `frame_camera`. A selection may have matched no atoms.

## License

MIT
