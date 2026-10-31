"""youtube-transcript-api fetch (fast path, no download). Usage: transcript_api.py <video_id> <out.json>.
Exit 0 + JSON {segments:[{start,dur,text}], generated, language} on success; exit 3 when unavailable/blocked."""
import json, sys, warnings
warnings.filterwarnings("ignore")
from youtube_transcript_api import YouTubeTranscriptApi

vid, out = sys.argv[1], sys.argv[2]
try:
    t = YouTubeTranscriptApi().fetch(video_id=vid, languages=["en", "en-US", "en-GB"])
except Exception as e:  # noqa: BLE001
    print(type(e).__name__ + ": " + str(e).strip().splitlines()[0][:200], file=sys.stderr); sys.exit(3)
segs = [{"start": round(s.start, 2), "dur": round(s.duration, 2), "text": s.text.replace("\n", " ").strip()} for s in t.snippets if s.text.strip()]
open(out, "w").write(json.dumps({"segments": segs, "generated": bool(getattr(t, "is_generated", False)), "language": getattr(t, "language_code", None)}))
print(len(segs))
