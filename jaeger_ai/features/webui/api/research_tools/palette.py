"""Dominant colour palette across video frames (Pillow median-cut). argv: out.json frame.jpg..."""
import json
import sys
from collections import Counter

from PIL import Image


def main():
    out, files = sys.argv[1], sys.argv[2:]
    c = Counter()
    for f in files:
        try:
            im = Image.open(f).convert("RGB").resize((96, 54))
        except OSError:
            continue
        q = im.quantize(colors=6, method=Image.Quantize.MEDIANCUT)
        pal = q.getpalette()[:18]
        for n, idx in q.getcolors():
            r, g, b = pal[idx * 3:idx * 3 + 3]
            c[(r // 16 * 16, g // 16 * 16, b // 16 * 16)] += n
    total = sum(c.values()) or 1
    top = [{"hex": "#%02x%02x%02x" % k, "share": round(v / total, 3)} for k, v in c.most_common(8)]
    json.dump({"frames": len(files), "palette": top}, open(out, "w"))


if __name__ == "__main__":
    main()
