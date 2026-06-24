# core/mscript_engine.py

import os
import re
from pathlib import Path
from typing import Optional

try:
    from PIL import Image, ImageSequence
except Exception:  # pragma: no cover - optional dependency
    Image = None  # type: ignore[assignment]
    ImageSequence = None  # type: ignore[assignment]

try:
    import imageio.v3 as imageio_v3
except Exception:  # pragma: no cover - optional dependency
    imageio_v3 = None  # type: ignore[assignment]

try:
    import imageio_ffmpeg
except Exception:  # pragma: no cover - optional dependency
    imageio_ffmpeg = None  # type: ignore[assignment]

# Import base classes from the new neutral location
from .mochi_animations import Script, Command

# --- Mscript Parser (v3.0) ---
class _MscriptParser:
    """Parses a .mscript file into resources and a list of main instructions."""
    def __init__(self, script_path: str):
        if not os.path.exists(script_path):
            raise FileNotFoundError(f"MochiScript file not found: {script_path}")
        
        self.instructions: list[dict[str, any]] = []
        self.resources: dict[int, str] = {}
        # A set of argument keys that are known to be colors and need parsing.
        self._color_keys = {'FG', 'BG', 'CLR', 'CLR2'}
        self._parse(script_path)

    def _parse(self, path: str):
        with open(path, 'r') as f:
            lines = f.readlines()

        current_section = None
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith('!'):
                continue

            # Check for section changes
            section_match = re.match(r'^\[(Header|Resources|Main) (start|end)\]$', stripped)
            if section_match:
                section, state = section_match.groups()
                current_section = section if state == 'start' else None
                continue

            if current_section == 'Resources':
                self._parse_resource_line(stripped)
            elif current_section == 'Main':
                self._parse_main_line(stripped)

    def _parse_resource_line(self, line: str):
        match = re.match(r"K\[(\d+)\]:\s*'([^']+)'", line)
        if match:
            res_id, res_path = match.groups()
            self.resources[int(res_id)] = res_path

    def _parse_main_line(self, line: str):
        parts = line.split(maxsplit=1)
        command = parts[0].upper()
        args_str = parts[1] if len(parts) > 1 else ""

        # Regex to find all KEY[value] pairs
        arg_matches = re.findall(r'([A-Z_]+)\[([^\]]*)\]', args_str)
        args = {key: val for key, val in arg_matches}

        # --- NEW: Normalize color arguments to integer lists ---
        for key in self._color_keys:
            if key in args and isinstance(args[key], str):
                try:
                    args[key] = [int(c.strip()) for c in args[key].split(',')]
                except (ValueError, AttributeError):
                    print(f"Warning: Could not parse color string '{args[key]}' for key '{key}'")
        
        self.instructions.append({'command': command, 'args': args})


# --- Mscript Engine (v3.0) ---
class MscriptScript(Script):
    """
    The V3.0 script implementation that reads and executes a .mscript file.
    It correctly handles the line-by-line flow control using WAIT commands.
    """
    def __init__(self, path: str):
        super().__init__(path)
        parser = _MscriptParser(path)
        self._instructions = parser.instructions
        self._resources = parser.resources
        # The asset root should be the project root, not the assets directory itself.
        # Assuming mscript files are always in assets/mscripts/.
        self._asset_root = Path(path).resolve().parent.parent.parent
        
        self._program_counter = 0
        self._wait_until = 0.0

    def update(self, t: float) -> list[Command]:
        if self._program_counter >= len(self._instructions):
            return [] # End of script

        if t < self._wait_until:
            return [] # Still waiting

        # Process all due commands until a WAIT is found
        due_commands: list[Command] = []
        while self._program_counter < len(self._instructions):
            instruction = self._instructions[self._program_counter]
            self._program_counter += 1

            cmd_name = instruction['command']
            raw_args = instruction['args']
            args = raw_args.copy()

            duration_token = args.pop('D', None)
            wait_after_command = self._parse_duration_token(duration_token, cmd_name, raw_args)
            if wait_after_command is None and cmd_name == 'MEDIA':
                wait_after_command = self._auto_duration_for_command(raw_args)

            # Handle WAIT command for timing control
            if cmd_name == 'WAIT':
                wait_duration = self._coerce_float(duration_token)
                if wait_duration is not None and wait_duration > 0:
                    self._wait_until = t + wait_duration
                # Stop processing for this frame and wait
                return due_commands

            # For all other commands, resolve the resource key if present
            if 'K' in args:
                try:
                    key = int(args['K'])
                except (TypeError, ValueError):
                    print(f"Warning: Invalid resource key '{args['K']}' for command {cmd_name}.")
                    continue  # Skip this invalid command
                resource_path = self._resources.get(key)
                if resource_path:
                    # Add asset_path to the arguments, just like the JSON engine
                    args['asset_path'] = resource_path
                else:
                    print(f"Warning: Resource key {key} not found in resources.")
                    continue # Skip this invalid command
            
            due_commands.append(Command(name=cmd_name, args=args))

            if wait_after_command is not None and wait_after_command > 0:
                self._wait_until = t + wait_after_command
                return due_commands

        return due_commands

    # ------------------------------------------------------------------ helpers
    def _coerce_float(self, value) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _parse_duration_token(self, token, cmd_name: str, raw_args: dict) -> Optional[float]:
        if token is None:
            return None

        # Accept numeric tokens directly
        duration = self._coerce_float(token)
        if duration is not None:
            return duration

        token_str = str(token).strip().lower()
        if token_str in {"auto", "asset"}:
            return self._auto_duration_for_command(raw_args)
        return None

    def _auto_duration_for_command(self, raw_args: dict) -> Optional[float]:
        key_raw = raw_args.get('K')
        if key_raw is None:
            return None
        try:
            key = int(key_raw)
        except (TypeError, ValueError):
            return None
        resource = self._resources.get(key)
        if not resource:
            return None
        full_path = self._resolve_resource_path(resource)
        if not full_path:
            return None
        suffix = full_path.suffix.lower()
        if suffix in {".mp4", ".mov", ".mkv", ".avi", ".webm"}:
            return self._video_duration(full_path)
        if suffix in {".gif", ".apng"}:
            return self._gif_duration(full_path)
        return None

    def _resolve_resource_path(self, resource: str) -> Optional[Path]:
        path = Path(resource)
        if path.is_absolute():
            return path if path.exists() else None
        candidate = self._asset_root / path
        if candidate.exists():
            return candidate
        return None

    def _video_duration(self, path: Path) -> Optional[float]:
        # Try imageio-ffmpeg first (count_frames_and_secs → (nframes, secs))
        if imageio_ffmpeg is not None:
            try:
                _nframes, secs = imageio_ffmpeg.count_frames_and_secs(str(path))
                if secs:
                    return float(secs)
            except Exception:
                pass

        if imageio_v3 is not None:
            for plugin in ("FFMPEG", None):
                try:
                    meta = imageio_v3.immeta(str(path), plugin=plugin) if plugin else imageio_v3.immeta(str(path))
                except Exception:
                    continue
                duration_val = meta.get("duration")
                if duration_val is not None:
                    try:
                        return float(duration_val)
                    except (TypeError, ValueError):
                        pass
                fps = meta.get("fps") or meta.get("framerate")
                nframes = meta.get("nframes")
                video_block = meta.get("video") or {}
                if not nframes:
                    nframes = video_block.get("nframes")
                if not fps:
                    fps = video_block.get("fps")
                try:
                    if fps and nframes:
                        fps_val = float(fps[0] / fps[1]) if isinstance(fps, (tuple, list)) else float(fps)
                        return float(nframes) / fps_val if fps_val > 0 else None
                except (TypeError, ValueError, ZeroDivisionError):
                    continue
        return None

    def _gif_duration(self, path: Path) -> Optional[float]:
        if Image is None or ImageSequence is None:
            return None
        try:
            with Image.open(str(path)) as img:
                total_ms = 0
                for frame in ImageSequence.Iterator(img):
                    total_ms += int(frame.info.get("duration", 100))
                return total_ms / 1000.0 if total_ms > 0 else None
        except Exception:
            return None
