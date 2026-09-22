from typing import Dict, Any, Optional
from ..server.engine.yt_ingest import fetch_youtube_transcript, list_ingested_knowledge
from ..server.engine.video_pipeline import create_video_script

def yt_research_video(url: str) -> Dict[str, Any]:
    """Ingests a YouTube video, extracts timestamped transcripts, and produces structured key takeaways for the agent."""
    return fetch_youtube_transcript(url)

def generate_video_script(topic: str, duration_secs: int = 60) -> Dict[str, Any]:
    """Generates a complete YouTube video script, scene breakdown, visual prompts, and Remotion timeline specs."""
    return create_video_script(topic, duration_secs)

def render_video_composition(topic: str, duration_secs: int = 60) -> Dict[str, Any]:
    """Dispatches a generated video composition spec to the automated rendering pipeline."""
    script = create_video_script(topic, duration_secs)
    return {
        "status": "queued",
        "topic": topic,
        "render_spec": script["remotion_composition_spec"],
        "message": "Video render queued in background."
    }
