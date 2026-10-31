"""On-screen text via Apple Vision (ocrmac). Usage: ocr_frames.py <frames_dir> <out.json> — runs in .venv-research."""
import json, sys
from pathlib import Path
from ocrmac import ocrmac

d, out = Path(sys.argv[1]), Path(sys.argv[2])
res = []
for f in sorted(d.glob("*.jpg")):
    try:
        items = ocrmac.OCR(str(f), recognition_level="accurate").recognize()
    except Exception as e:  # noqa: BLE001
        res.append({"file": f.name, "error": str(e)[:200], "lines": []}); continue
    lines = [{"text": t, "conf": round(float(c), 3), "bbox": [round(float(x), 3) for x in b]} for t, c, b in items if float(c) >= 0.4 and t.strip()]
    res.append({"file": f.name, "lines": lines, "text": " | ".join(l["text"] for l in lines)})
out.write_text(json.dumps(res, ensure_ascii=False, indent=1))
print(json.dumps({"frames": len(res), "with_text": sum(1 for r in res if r.get("lines"))}))
