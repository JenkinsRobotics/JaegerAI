import os
import json
from typing import Dict, Any, List

def build_remotion_project_manifest(script_data: Dict[str, Any], template_type: str = "shorts_9_16") -> Dict[str, Any]:
    """Builds a complete Remotion JSX composition schema ready for automated rendering."""
    is_vertical = template_type == "shorts_9_16"
    width = 1080 if is_vertical else 1920
    height = 1920 if is_vertical else 1080
    fps = 30
    duration_secs = script_data.get("target_duration_secs", 60)
    
    composition = {
        "id": f"Comp_{abs(hash(script_data['topic'])) % 10000}",
        "template": template_type,
        "width": width,
        "height": height,
        "fps": fps,
        "durationInFrames": duration_secs * fps,
        "props": {
            "title": script_data.get("title_ideas", ["Untitled"])[0],
            "topic": script_data["topic"],
            "hook": script_data.get("hook", ""),
            "scenes": script_data.get("scenes", []),
            "theme": {
                "primaryColor": "#00e5ff",
                "accentColor": "#b388ff",
                "backgroundColor": "#0a0e17",
                "fontFamily": "Inter, sans-serif"
            }
        },
        "render_command": f"npx remotion render src/index.ts {template_type} out/video.mp4 --props='...' "
    }
    return composition
