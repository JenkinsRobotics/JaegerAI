const API_BASE = "http://127.0.0.1:3849";

// Tab Navigation
document.querySelectorAll(".nav-tab").forEach(tabBtn => {
  tabBtn.addEventListener("click", () => {
    document.querySelectorAll(".nav-tab").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
    
    tabBtn.classList.add("active");
    const targetId = tabBtn.getAttribute("data-tab");
    document.getElementById(targetId).classList.add("active");
  });
});

// Three.js 3D Avatar Viewport in Dashboard
let scene, camera, renderer, headGroup, mouthMesh;
let isLipSyncing = false;

function init3DStage() {
  const container = document.getElementById("threeStage");
  if (!container) return;
  
  scene = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(45, container.clientWidth / container.clientHeight, 0.1, 1000);
  camera.position.set(0, 1.0, 3.2);

  renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
  renderer.setSize(container.clientWidth, container.clientHeight);
  renderer.setPixelRatio(window.devicePixelRatio);
  container.appendChild(renderer.domElement);

  // Lights
  const ambient = new THREE.AmbientLight(0xffffff, 0.8);
  scene.add(ambient);
  const point = new THREE.PointLight(0x00e5ff, 1.8, 50);
  point.position.set(2, 3, 4);
  scene.add(point);

  // Avatar Model
  headGroup = new THREE.Group();

  const headGeo = new THREE.SphereGeometry(0.65, 32, 32);
  const headMat = new THREE.MeshStandardMaterial({ color: 0x18243c, roughness: 0.2, metalness: 0.8 });
  const head = new THREE.Mesh(headGeo, headMat);
  headGroup.add(head);

  const visorGeo = new THREE.BoxGeometry(0.75, 0.18, 0.3);
  const visorMat = new THREE.MeshBasicMaterial({ color: 0x00e5ff });
  const visor = new THREE.Mesh(visorGeo, visorMat);
  visor.position.set(0, 0.08, 0.55);
  headGroup.add(visor);

  const mouthGeo = new THREE.BoxGeometry(0.28, 0.04, 0.1);
  const mouthMat = new THREE.MeshBasicMaterial({ color: 0xb388ff });
  mouthMesh = new THREE.Mesh(mouthGeo, mouthMat);
  mouthMesh.position.set(0, -0.28, 0.55);
  headGroup.add(mouthMesh);

  const bodyGeo = new THREE.CylinderGeometry(0.45, 0.65, 1.0, 32);
  const bodyMat = new THREE.MeshStandardMaterial({ color: 0x0f1828, roughness: 0.3, metalness: 0.7 });
  const body = new THREE.Mesh(bodyGeo, bodyMat);
  body.position.y = -1.1;
  headGroup.add(body);

  headGroup.position.y = 0.2;
  scene.add(headGroup);

  const clock = new THREE.Clock();
  function animate() {
    requestAnimationFrame(animate);
    const t = clock.getElapsedTime();

    if (document.getElementById("tiltCheck")?.checked) {
      headGroup.position.y = 0.2 + Math.sin(t * 1.5) * 0.03;
      headGroup.rotation.y = Math.sin(t * 0.8) * 0.15;
      headGroup.rotation.x = Math.sin(t * 1.2) * 0.05;
    }

    if (isLipSyncing && document.getElementById("visemeCheck")?.checked) {
      mouthMesh.scale.y = 1.0 + Math.abs(Math.sin(t * 10.0)) * 3.0;
    } else {
      mouthMesh.scale.y = 1.0;
    }

    renderer.render(scene, camera);
  }
  animate();

  window.addEventListener('resize', () => {
    if (!container) return;
    camera.aspect = container.clientWidth / container.clientHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(container.clientWidth, container.clientHeight);
  });
}

// Copy OBS Overlay URL
document.getElementById("copyObsBtn").addEventListener("click", () => {
  navigator.clipboard.writeText("http://127.0.0.1:3849/overlay/avatar");
  const btn = document.getElementById("copyObsBtn");
  btn.innerText = "✅ Copied to Clipboard!";
  setTimeout(() => { btn.innerText = "📋 Copy OBS Overlay URL"; }, 2500);
});

// Toggle Lip Sync
document.getElementById("toggleLipSyncBtn").addEventListener("click", () => {
  isLipSyncing = !isLipSyncing;
  const btn = document.getElementById("toggleLipSyncBtn");
  btn.innerText = isLipSyncing ? "⏹ Stop Lip-Sync" : "🔊 Test Speech Lip-Sync";
});

// Webcam toggle
let webcamActive = false;
document.getElementById("toggleWebcamBtn").addEventListener("click", async () => {
  const btn = document.getElementById("toggleWebcamBtn");
  if (!webcamActive) {
    try {
      await navigator.mediaDevices.getUserMedia({ video: true });
      webcamActive = true;
      btn.innerText = "⏹ Stop Webcam Tracking";
      btn.className = "btn-accent";
    } catch (e) {
      alert("Webcam access not granted or not available in this window.");
    }
  } else {
    webcamActive = false;
    btn.innerText = "📷 Enable Webcam Tracking";
    btn.className = "btn-primary";
  }
});

// Video Script & Remotion Generator
let currentScriptData = null;
document.getElementById("generateScriptBtn").addEventListener("click", async () => {
  const topic = document.getElementById("videoTopicInput").value.trim() || "Autonomous Agent Robotics in 2026";
  const btn = document.getElementById("generateScriptBtn");
  btn.innerText = "Generating Script & Scenes...";
  
  try {
    const res = await fetch(`${API_BASE}/api/video/script`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ topic, duration_secs: 60 })
    });
    const data = await res.json();
    currentScriptData = data;
    
    const container = document.getElementById("storyboardContainer");
    container.innerHTML = "";
    
    data.scenes.forEach(scene => {
      const div = document.createElement("div");
      div.className = "scene-card";
      div.innerHTML = `
        <div class="scene-title">Scene ${scene.scene_number} (${scene.timestamp_start} - ${scene.timestamp_end})</div>
        <div class="scene-voiceover">"${scene.voiceover_text}"</div>
        <div class="scene-prompt">🎬 Visual Prompt: ${scene.visual_prompt}</div>
      `;
      container.appendChild(div);
    });
    
    document.getElementById("renderSpecsBox").innerHTML = `
      <pre>${JSON.stringify(data.remotion_manifest, null, 2)}</pre>
    `;
  } catch (err) {
    console.error("Script generation failed", err);
  } finally {
    btn.innerText = "✨ Generate Script & Remotion Schema";
  }
});

document.getElementById("exportMp4Btn").addEventListener("click", () => {
  if (!currentScriptData) {
    alert("Please generate a video script first!");
    return;
  }
  const cmd = currentScriptData.remotion_manifest?.render_command || "npx remotion render ...";
  navigator.clipboard.writeText(cmd);
  alert("Render command copied to clipboard:\n" + cmd);
});

// YouTube Ingestion
document.getElementById("learnYtBtn").addEventListener("click", async () => {
  const url = document.getElementById("ytUrlInput").value.trim();
  if (!url) return;
  
  const btn = document.getElementById("learnYtBtn");
  btn.innerText = "Ingesting Video...";
  
  try {
    const res = await fetch(`${API_BASE}/api/yt/learn`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url })
    });
    const data = await res.json();
    
    const resultsContainer = document.getElementById("learningResults");
    resultsContainer.innerHTML = `
      <h3 style="color: var(--accent-cyan); margin-bottom: 8px;">✅ Ingested: ${data.video_id} (${data.word_count} words)</h3>
      <p style="font-size: 13px; margin-bottom: 10px;">${data.summary}</p>
      <h4 style="font-size: 12px; color: var(--text-secondary);">Key Takeaways:</h4>
      <ul style="font-size: 12px; margin-left: 18px; color: var(--text-primary); margin-top: 6px;">
        ${data.key_takeaways.map(t => `<li>${t}</li>`).join("")}
      </ul>
    `;
    loadLibrary();
  } catch (err) {
    console.error("Ingestion failed", err);
  } finally {
    btn.innerText = "🧠 Ingest";
  }
});

async function loadLibrary() {
  try {
    const res = await fetch(`${API_BASE}/api/yt/knowledge`);
    if (!res.ok) return;
    const data = await res.json();
    
    const list = document.getElementById("knowledgeLibraryList");
    list.innerHTML = "";
    document.getElementById("libraryCount").innerText = `${data.library.length} Videos`;
    
    data.library.forEach(item => {
      const div = document.createElement("div");
      div.className = "library-item";
      div.innerHTML = `
        <strong>${item.video_id}</strong> (${item.word_count} words)
        <div style="color: var(--text-secondary); font-size: 11px; margin-top: 2px;">${item.summary}</div>
      `;
      list.appendChild(div);
    });
  } catch (err) {
    console.error("Failed to load library", err);
  }
}

init3DStage();
loadLibrary();
