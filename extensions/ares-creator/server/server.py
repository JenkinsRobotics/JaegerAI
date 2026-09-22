import os
import json
import uvicorn
from fastapi import FastAPI, Query, Body, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from .engine.yt_ingest import fetch_youtube_transcript, list_ingested_knowledge
from .engine.video_pipeline import create_video_script
from .engine.remotion_builder import build_remotion_project_manifest

app = FastAPI(title="ARES Creator Studio Sidecar", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "ares-creator",
        "version": "1.0.0",
        "capabilities": ["vtuber_overlay", "youtube_learning", "video_pipeline", "remotion_builder"]
    }

class YouTubeLearnRequest(BaseModel):
    url: str

@app.post("/api/yt/learn")
def learn_youtube_video(req: YouTubeLearnRequest):
    return fetch_youtube_transcript(req.url)

@app.get("/api/yt/knowledge")
def get_knowledge_library():
    return {"library": list_ingested_knowledge()}

class VideoScriptRequest(BaseModel):
    topic: str
    duration_secs: Optional[int] = 60

@app.post("/api/video/script")
def generate_video_script(req: VideoScriptRequest):
    script = create_video_script(req.topic, req.duration_secs or 60)
    remotion_manifest = build_remotion_project_manifest(script, "shorts_9_16")
    script["remotion_manifest"] = remotion_manifest
    return script

@app.get("/overlay/avatar", response_class=HTMLResponse)
def get_obs_transparent_overlay():
    """Returns a transparent OBS Browser Source viewport with a live Three.js 3D avatar & audio visemes."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <title>ARES 3D VTuber OBS Overlay</title>
      <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
      <style>
        body { margin: 0; background: transparent; overflow: hidden; }
        #canvas3d { width: 100vw; height: 100vh; display: block; }
        .hud-watermark {
          position: absolute; bottom: 12px; right: 12px;
          color: rgba(0, 229, 255, 0.4); font-family: monospace; font-size: 11px;
        }
      </style>
    </head>
    <body>
      <div id="container"></div>
      <div class="hud-watermark">ARES VTUBER • OBS STREAM OVERLAY</div>
      <script>
        const scene = new THREE.Scene();
        const camera = new THREE.PerspectiveCamera(45, window.innerWidth / window.innerHeight, 0.1, 1000);
        camera.position.set(0, 1.2, 3.5);

        const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
        renderer.setSize(window.innerWidth, window.innerHeight);
        renderer.setPixelRatio(window.devicePixelRatio);
        document.body.appendChild(renderer.domElement);

        // Lighting
        const ambientLight = new THREE.AmbientLight(0xffffff, 0.8);
        scene.add(ambientLight);
        const pointLight = new THREE.PointLight(0x00e5ff, 1.5, 50);
        pointLight.position.set(2, 3, 4);
        scene.add(pointLight);

        // Avatar Robot Head
        const headGroup = new THREE.Group();
        
        const headGeo = new THREE.SphereGeometry(0.7, 32, 32);
        const headMat = new THREE.MeshStandardMaterial({ color: 0x18243c, roughness: 0.2, metalness: 0.8 });
        const headMesh = new THREE.Mesh(headGeo, headMat);
        headGroup.add(headMesh);

        // Cyber Visor / Eyes
        const visorGeo = new THREE.BoxGeometry(0.8, 0.2, 0.3);
        const visorMat = new THREE.MeshBasicMaterial({ color: 0x00e5ff });
        const visor = new THREE.Mesh(visorGeo, visorMat);
        visor.position.set(0, 0.1, 0.6);
        headGroup.add(visor);

        // Mouth (Viseme target)
        const mouthGeo = new THREE.BoxGeometry(0.3, 0.05, 0.1);
        const mouthMat = new THREE.MeshBasicMaterial({ color: 0xb388ff });
        const mouth = new THREE.Mesh(mouthGeo, mouthMat);
        mouth.position.set(0, -0.3, 0.6);
        headGroup.add(mouth);

        // Body Torso
        const bodyGeo = new THREE.CylinderGeometry(0.5, 0.7, 1.2, 32);
        const bodyMat = new THREE.MeshStandardMaterial({ color: 0x0f1828, roughness: 0.3, metalness: 0.7 });
        const bodyMesh = new THREE.Mesh(bodyGeo, bodyMat);
        bodyMesh.position.y = -1.2;
        headGroup.add(bodyMesh);

        headGroup.position.y = 0.3;
        scene.add(headGroup);

        // Audio Speech Lip-Sync simulation
        let clock = new THREE.Clock();
        function animate() {
          requestAnimationFrame(animate);
          const t = clock.getElapsedTime();

          // Subtle floating idle motion
          headGroup.position.y = 0.3 + Math.sin(t * 1.5) * 0.04;
          headGroup.rotation.y = Math.sin(t * 0.8) * 0.1;
          headGroup.rotation.x = Math.sin(t * 1.2) * 0.05;

          // Mouth viseme flap
          mouth.scale.y = 1.0 + Math.abs(Math.sin(t * 8.0)) * 2.5;

          renderer.render(scene, camera);
        }
        animate();

        window.addEventListener('resize', () => {
          camera.aspect = window.innerWidth / window.innerHeight;
          camera.updateProjectionMatrix();
          renderer.setSize(window.innerWidth, window.innerHeight);
        });
      </script>
    </body>
    </html>
    """

if __name__ == "__main__":
    port = int(os.getenv("CREATOR_PORT", 3849))
    uvicorn.run(app, host="127.0.0.1", port=port)
