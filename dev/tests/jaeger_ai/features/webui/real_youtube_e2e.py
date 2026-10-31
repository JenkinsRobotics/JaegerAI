"""REAL end-to-end run of the YouTube research pipeline against the LIVE WebUI on 127.0.0.1:8790.
Not collected by pytest (no test_ prefix). Hits YouTube (public playlist), yt-dlp, ffmpeg, Ollama for real.
Usage: ~/.jaeger/venv/bin/python dev/tests/jaeger_ai/features/webui/real_youtube_e2e.py <playlist_url> [max_videos] [model] [topic]
The CSRF token is read from the served page the same way the browser does and is never printed."""
import http.cookiejar, json, re, sys, time, urllib.request

BASE = "http://127.0.0.1:8790"
jar = http.cookiejar.CookieJar(); op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
html = op.open(BASE + "/work", timeout=10).read().decode()
m = re.search(r'name="jaeger-csrf"\s+content="([^"]+)"', html) or re.search(r'content="([^"]+)"\s+name="jaeger-csrf"', html)
H = {"Content-Type": "application/json", **({"X-Hermes-CSRF-Token": m.group(1)} if m else {})}

def call(method, path, body=None, timeout=900):
    req = urllib.request.Request(BASE + path, data=None if body is None else json.dumps(body).encode(), method=method, headers=H)
    try:
        with op.open(req, timeout=timeout) as r: return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or b"{}")

url = sys.argv[1]; n = int(sys.argv[2]) if len(sys.argv) > 2 else 3
model = sys.argv[3] if len(sys.argv) > 3 else None; topic = sys.argv[4] if len(sys.argv) > 4 else "A 60-second weeknight pasta trick"
print("[REAL] tools", call("GET", "/v1/research/youtube/tools"))
t0 = time.time(); s, j = call("POST", "/v1/research/youtube", {"playlist_url": url, "max_videos": n, **({"model": model} if model else {})})
print("[REAL] ingest", s, j.get("task_id"), j.get("playlist_title"), len(j.get("videos", [])), "videos; model", j.get("model"))
tid = j["task_id"]
while True:
    s, j = call("GET", "/v1/research/youtube/" + urllib.request.quote(tid, safe=":"))
    print(f"[REAL] {time.time()-t0:5.0f}s state={j['state']} progress={j['progress']} guide={j['style_guide'].get('status')}", flush=True)
    if not j["running"]: break
    time.sleep(15)
for v in j["videos"]:
    print("[REAL] video", v["id"], (v["title"] or "")[:50], {k: (x.get("status"), x.get("source") or x.get("reason") or x.get("error")) for k, x in v["steps"].items()})
s, g = call("GET", f"/v1/research/youtube/{tid}/style-guide")
print("[REAL] style-guide", s); print(g.get("markdown", g)[:3000] if s == 200 else g)
s, d = call("POST", f"/v1/research/youtube/{tid}/draft", {"topic": topic})
print("[REAL] draft", s); print(d.get("markdown", d)[:2000] if s == 201 else d)
s, p = call("GET", "/v1/pipeline"); r = p["items"].get(tid, {})
print("[REAL] pipeline stage", r.get("stage"), "attachments", [(a["kind"], a.get("label")) for a in r.get("attachments", [])])
print(f"[REAL] total {time.time()-t0:.0f}s")
