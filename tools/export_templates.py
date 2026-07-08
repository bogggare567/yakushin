"""
Turns clustered glyph bitmaps (from extract_glyph_templates.py) into the packed-hex
templates baked into webapp/glyph-templates.js.

Usage:
    python export_templates.py <clusters_dir_with_clusters.npz> <output_glyph-templates.js>

Before running: open <clusters_dir>/cluster_NN_nCOUNT.png for each NN and edit `LABEL_MAP`
below so it says what digit (or "x") that cluster actually shows. The mapping below is the
one used to generate the glyph-templates.js currently shipped in webapp/, from
2.2-Super Yacht Deck 1 STERN 2.pdf pages 5-692 - re-derive it if you regenerate clusters
from a different document/font.

No "9" ever appeared in that page range, so it's synthesized as a 180-degree rotation of the
"6" cluster (works because this font's digits are simple/geometric). If your document does
have real "9" samples, add its cluster index to LABEL_MAP instead and delete the synthesis step.
"""
import numpy as np
import sys

LABEL_MAP = {
    0: "x", 1: "1", 2: "2", 3: "4", 4: "3", 5: "4", 6: "6", 7: "x",
    8: "0", 9: "5", 10: "8", 11: "3", 12: "x", 13: "7", 17: "8", 19: "6",
}
SYNTHESIZE_NINE_FROM_SIX = True  # set False once a real "9" cluster is in LABEL_MAP


def pack_hex(bits):
    s = "".join(str(b) for b in bits)
    s += "0" * ((-len(s)) % 4)
    return "".join(format(int(s[i:i + 4], 2), "x") for i in range(0, len(s), 4))


def main():
    if len(sys.argv) != 3:
        print(f"Usage: python {sys.argv[0]} <clusters_dir> <output_glyph-templates.js>")
        sys.exit(1)
    clusters_dir, out_path = sys.argv[1], sys.argv[2]
    data = np.load(f"{clusters_dir}/clusters.npz")

    templates = [(label, data[f"arr_{idx}"]) for idx, label in LABEL_MAP.items()]
    if SYNTHESIZE_NINE_FROM_SIX:
        six = data["arr_6"]
        templates.append(("9", six[::-1, ::-1]))

    h, w = templates[0][1].shape
    lines = [
        f"// Auto-generated digit glyph templates ({h}x{w} binary bitmaps, packed as hex).",
        "// Regenerate with tools/extract_glyph_templates.py + tools/export_templates.py.",
        f"const GLYPH_H = {h}, GLYPH_W = {w};",
        "const GLYPH_TEMPLATES = [",
    ]
    for label, bm in templates:
        bits = bm.flatten().astype(int).tolist()
        lines.append(f'  {{ label: "{label}", bits: "{pack_hex(bits)}", n: {len(bits)} }},')
    lines.append("];")

    with open(out_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote {len(templates)} templates -> {out_path}")


if __name__ == "__main__":
    main()
