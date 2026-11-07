"""Zip the Blender add-on into dist/protein_blender_mcp.zip for Install from Disk."""

import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "addon" / "protein_blender_mcp"
OUT = ROOT / "dist" / "protein_blender_mcp.zip"

OUT.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zf:
    for path in sorted(SRC.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            zf.write(path, path.relative_to(SRC))
print(f"Wrote {OUT}")
