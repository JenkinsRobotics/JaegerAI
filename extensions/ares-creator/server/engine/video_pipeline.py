import os
import json
from typing import Dict, Any, List

SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "scripts")

def create_video_script(topic: str, target_duration_secs: int = 60) -> Dict[str, Any]:
    os.makedirs(SCRIPTS_DIR, exist_ok=True)
    
    # Formulate structured script template
    script_data = {
        "topic": topic,
        "target_duration_secs": target_duration_secs,
        "title_ideas": [
            f"How We Automated {topic} with AI",
            f"The Ultimate Guide to {topic} in 2026",
            f"Why Everyone is Wrong About {topic}"
        ],
        "hook": f"Did you know that {topic} can now be completely automated using agentic workflows? In the next 60 seconds, I'll show you exactly how.",
        "scenes": [
            {
                "scene_number": 1,
                "timestamp_start": "00:00",
                "timestamp_end": "00:15",
                "visual_prompt": f"Dynamic kinetic typography showing key metrics of {topic}, fast cuts with dark tech aesthetic.",
                "voiceover_text": f"Most creators spend hours manually producing content for {topic}. But with autonomous pipelines, that changes today.",
                "broll_tags": ["cyberpunk", "dashboard", "fast_code"]
            },
            {
                "scene_number": 2,
                "timestamp_start": "00:15",
                "timestamp_end": "00:45",
                "visual_prompt": "Split screen: VTuber avatar live tracking on left, code & architecture diagram on right.",
                "voiceover_text": f"Here is the exact three-step blueprint for {topic}. First, ingest the data. Second, compose the Remotion timeline. Third, render directly to MP4.",
                "broll_tags": ["architecture", "remotion", "pipeline"]
            },
            {
                "scene_number": 3,
                "timestamp_start": "00:45",
                "timestamp_end": "01:00",
                "visual_prompt": "Call to action card with animated subscribe button and community links.",
                "voiceover_text": "Drop a comment with your favorite feature, and hit subscribe for more agent workflows.",
                "broll_tags": ["outro", "subscribe", "glow"]
            }
        ],
        "remotion_composition_spec": {
            "fps": 30,
            "width": 1920,
            "height": 1080,
            "durationInFrames": target_duration_secs * 30
        }
    }
    
    file_path = os.path.join(SCRIPTS_DIR, f"script_{abs(hash(topic)) % 10000}.json")
    with open(file_path, "w") as f:
        json.dump(script_data, f, indent=2)
        
    return script_data
