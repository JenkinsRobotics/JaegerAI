#!/usr/bin/env python3
"""
Alexandria Apple Data Export — Autonomous Pipeline

Pulls Apple Notes, Reminders, and Calendar events via AppleScript,
enriches each with Claude (summary, action items, entities, tags),
and writes enriched markdown to the NAS Alexandria/sources directory.

Runs as a background process. Progress logged to /tmp/alexandria_apple_export.log
"""

import subprocess
import json
import os
import re
import time
import hashlib
from pathlib import Path
from datetime import datetime

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SOURCES_DIR = "/Volumes/Jenkins_Robotics-1/Alexandria/sources"
LOG_FILE = "/tmp/alexandria_apple_export.log"
PROGRESS_FILE = "/tmp/alexandria_apple_export_progress.json"
CLAUDE_PATH = "/opt/homebrew/bin/claude"

NOTES_DIR = os.path.join(SOURCES_DIR, "notes")
REMINDERS_DIR = os.path.join(SOURCES_DIR, "reminders")
CALENDAR_DIR = os.path.join(SOURCES_DIR, "calendar")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def log(msg):
    ts = datetime.now().isoformat()
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def save_progress(progress):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, indent=2)

# ---------------------------------------------------------------------------
# AppleScript helpers
# ---------------------------------------------------------------------------
def run_applescript(script, timeout=60):
    """Run AppleScript and return stdout."""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=timeout,
            stdin=subprocess.DEVNULL
        )
        return result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        return "", "timeout", -1

def run_applescript_file(script_content, timeout=120):
    """Run AppleScript from a file (for large scripts)."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.scpt', delete=False) as f:
        f.write(script_content)
        f.flush()
        try:
            result = subprocess.run(
                ["osascript", f.name],
                capture_output=True, text=True, timeout=timeout,
                stdin=subprocess.DEVNULL
            )
            return result.stdout, result.stderr, result.returncode
        except subprocess.TimeoutExpired:
            return "", "timeout", -1
        finally:
            os.unlink(f.name)

import tempfile

# ---------------------------------------------------------------------------
# HTML to text conversion (Apple Notes stores body as HTML)
# ---------------------------------------------------------------------------
def html_to_text(html):
    """Convert Apple Notes HTML to clean text."""
    if not html:
        return ""
    # Remove HTML tags
    text = re.sub(r'<br\s*/?>', '\n', html, flags=re.IGNORECASE)
    text = re.sub(r'</div>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</li>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<li[^>]*>', '• ', text, flags=re.IGNORECASE)
    text = re.sub(r'<h[1-6][^>]*>', '\n## ', text, flags=re.IGNORECASE)
    text = re.sub(r'</h[1-6]>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<b[^>]*>', '**', text, flags=re.IGNORECASE)
    text = re.sub(r'</b>', '**', text, flags=re.IGNORECASE)
    text = re.sub(r'<i[^>]*>', '*', text, flags=re.IGNORECASE)
    text = re.sub(r'</i>', '*', text, flags=re.IGNORECASE)
    text = re.sub(r'<a[^>]*href="([^"]*)"[^>]*>([^<]*)</a>', r'[\2](\1)', text, flags=re.IGNORECASE)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'&lt;', '<', text)
    text = re.sub(r'&gt;', '>', text)
    text = re.sub(r'&quot;', '"', text)
    text = re.sub(r'&#39;', "'", text)
    text = re.sub(r'&nbsp;', ' ', text)
    # Remove remaining tags
    text = re.sub(r'<[^>]+>', '', text)
    # Clean up whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip()
    return text

# ---------------------------------------------------------------------------
# Claude enrichment
# ---------------------------------------------------------------------------
def enrich_with_claude(note_name, note_text, item_type="note"):
    """Send note to Claude for enrichment. Returns dict with summary, category, action_items, entities, tags."""
    
    # Truncate very long notes for the enrichment prompt
    max_chars = 30000
    truncated = note_text[:max_chars]
    if len(note_text) > max_chars:
        truncated += "\n\n[... truncated for enrichment, full content preserved in file ...]"
    
    prompt = f"""Analyze this {item_type} and return a JSON object with the following fields:
- title: A clear, descriptive title (rewrite if the original is vague like "New Note" or "New Recording")
- summary: 1-2 sentence summary of what this {item_type} is actually about
- category: One of: "quantum-space", "jenkins-robotics", "personal", "finance", "travel", "health", "tech", "system", "archive"
- action_items: Array of any tasks, decisions, or deadlines mentioned (empty array if none)
- entities: Array of named entities mentioned (people, dates, amounts, project names, contract numbers)
- tags: Array of 3-8 meaningful semantic tags from this vocabulary: robotics, firmware, hardware, contract, finance, proposal, report, legal, travel, health, system, config, credentials, meeting, reference, archive, personal, journal, todo, video, design, research
- status: "active", "draft", or "archived" based on content and context
- sensitive: true if this contains passwords, credentials, or financial details, false otherwise

Return ONLY the JSON object, no preamble or explanation.

{item_type.title()} content:
Title: {note_name}

{truncated}"""

    try:
        result = subprocess.run(
            [CLAUDE_PATH, "-p", prompt, "--output-format", "json"],
            capture_output=True, text=True, timeout=60,
            stdin=subprocess.DEVNULL,
            cwd=os.path.expanduser("~/workspace")
        )
        if result.returncode == 0 and result.stdout.strip():
            # Try to parse the JSON output
            output = result.stdout.strip()
            # Claude sometimes wraps JSON in markdown code blocks
            if output.startswith("```"):
                output = re.sub(r'^```(?:json)?\n?', '', output)
                output = re.sub(r'\n?```$', '', output)
            return json.loads(output)
        else:
            log(f"  Claude enrichment failed: {result.stderr[:200]}")
            return None
    except subprocess.TimeoutExpired:
        log(f"  Claude enrichment timed out")
        return None
    except json.JSONDecodeError as e:
        log(f"  Claude JSON parse failed: {e}")
        return None
    except Exception as e:
        log(f"  Claude enrichment error: {e}")
        return None

# ---------------------------------------------------------------------------
# Write enriched markdown
# ---------------------------------------------------------------------------
def sanitize_filename(name):
    """Make a string safe for use as a filename."""
    # Remove emoji and special chars
    name = re.sub(r'[^\w\s\-]', '', name)
    name = re.sub(r'\s+', '_', name.strip())
    name = name[:80]  # Limit length
    return name if name else "untitled"

def write_enriched_markdown(filepath, frontmatter, body_text):
    """Write a markdown file with YAML frontmatter."""
    # Build YAML frontmatter
    yaml_lines = []
    for key, value in frontmatter.items():
        if isinstance(value, list):
            yaml_lines.append(f"{key}:")
            for item in value:
                yaml_lines.append(f"  - {json.dumps(item) if isinstance(item, str) and ('#' in item or ':' in item) else item}")
        elif isinstance(value, bool):
            yaml_lines.append(f"{key}: {str(value).lower()}")
        elif value is None or value == "":
            yaml_lines.append(f"{key}: \"\"")
        else:
            # Escape strings that contain special chars
            if isinstance(value, str) and (':' in value or '#' in value or '{' in value):
                yaml_lines.append(f'{key}: "{value}"')
            else:
                yaml_lines.append(f"{key}: {value}")
    
    yaml_block = "---\n" + "\n".join(yaml_lines) + "\n---\n\n"
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(yaml_block)
        f.write(body_text)
    
    return os.path.getsize(filepath)

# ---------------------------------------------------------------------------
# Apple Notes export
# ---------------------------------------------------------------------------
def get_all_note_metadata():
    """Get all note IDs, names, and folders."""
    script = '''
tell application "Notes"
set output to ""
repeat with f in folders
    set fname to name of f
    repeat with n in notes of f
        try
            set noteId to id of n
            set noteName to name of n
            set output to output & "FOLDER:" & fname & "|ID:" & noteId & "|NAME:" & noteName & "\\n"
        end try
    end repeat
end repeat
return output
end tell'''
    stdout, stderr, rc = run_applescript(script, timeout=30)
    notes = []
    for line in stdout.strip().split('\n'):
        if not line.startswith('FOLDER:'):
            continue
        parts = line.split('|')
        folder = parts[0].replace('FOLDER:', '')
        note_id = parts[1].replace('ID:', '') if len(parts) > 1 else ''
        note_name = parts[2].replace('NAME:', '') if len(parts) > 2 else ''
        notes.append({'folder': folder, 'id': note_id, 'name': note_name})
    return notes

def fetch_note_body(note_id, timeout=15):
    """Fetch a single note's body by ID."""
    script = f'''
tell application "Notes"
try
    set n to note id "{note_id}"
    set noteName to name of n
    set noteBody to body of n
    set noteCreated to creation date of n
    set noteMod to modification date of n
    return "NAME:" & noteName & "\\nCREATED:" & (noteCreated as string) & "\\nMODIFIED:" & (noteMod as string) & "\\n===BODY===\\n" & noteBody
on error errMsg
    return "ERROR:" & errMsg
end try
end tell'''
    stdout, stderr, rc = run_applescript(script, timeout=timeout)
    return stdout, stderr, rc

# ---------------------------------------------------------------------------
# Apple Reminders export
# ---------------------------------------------------------------------------
def get_all_reminders():
    """Get all reminders via AppleScript."""
    script = '''
tell application "Reminders"
set output to ""
repeat with l in lists
    set lname to name of l
    repeat with r in reminders of l
        try
            set rName to name of r
            set rBody to body of r
            set rDue to due date of r
            set rCompleted to completed of r
            set rPriority to priority of r
            set rDate to creation date of r
            
            set dueStr to "none"
            try
                if rDue is not missing value then set dueStr to (rDue as string)
            end try
            
            set output to output & "LIST:" & lname & "|NAME:" & rName & "|DUE:" & dueStr & "|COMPLETED:" & rCompleted & "|PRIORITY:" & rPriority & "|CREATED:" & (rDate as string) & "|BODY:" & rBody & "\\n===END==="
        on error errMsg
            set output to output & "LIST:" & lname & "|ERROR:" & errMsg & "\\n===END==="
        end try
    end repeat
end repeat
return output
end tell'''
    stdout, stderr, rc = run_applescript(script, timeout=60)
    reminders = []
    for block in stdout.split('===END==='):
        block = block.strip()
        if not block.startswith('LIST:'):
            continue
        fields = {}
        parts = block.split('|')
        for part in parts:
            if ':' in part:
                key, value = part.split(':', 1)
                fields[key] = value
        reminders.append(fields)
    return reminders

# ---------------------------------------------------------------------------
# Apple Calendar export
# ---------------------------------------------------------------------------
def get_calendar_events():
    """Get calendar events for next 90 days and past 30 days."""
    script = '''
tell application "Calendar"
set output to ""
set today to current date
set pastDate to today - (30 * days)
set futureDate to today + (90 * days)
repeat with c in calendars
    set cname to name of c
    set events to (every event of c whose start date is greater than pastDate and start date is less than futureDate)
    repeat with e in events
        try
            set eName to name of e
            set eStart to start date of e
            set eEnd to end date of e
            set eAllDay to allday event of e
            set eLocation to location of e
            set eNotes to description of e
            set eCal to cname
            
            set locStr to "none"
            if eLocation is not missing value then set locStr to eLocation
            set notesStr to "none"
            if eNotes is not missing value then set notesStr to eNotes
            
            set output to output & "CAL:" & eCal & "|NAME:" & eName & "|START:" & (eStart as string) & "|END:" & (eEnd as string) & "|ALLDAY:" & eAllDay & "|LOCATION:" & locStr & "|NOTES:" & notesStr & "\\n===END==="
        on error errMsg
            set output to output & "CAL:" & cname & "|ERROR:" & errMsg & "\\n===END==="
        end try
    end repeat
end repeat
return output
end tell'''
    stdout, stderr, rc = run_applescript(script, timeout=60)
    events = []
    for block in stdout.split('===END==='):
        block = block.strip()
        if not block.startswith('CAL:'):
            continue
        fields = {}
        parts = block.split('|')
        for part in parts:
            if ':' in part:
                key, value = part.split(':', 1)
                fields[key] = value
        events.append(fields)
    return events

# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
def main():
    log("=" * 60)
    log("Alexandria Apple Data Export — Starting")
    log("=" * 60)
    
    # Create directories
    for d in [NOTES_DIR, REMINDERS_DIR, CALENDAR_DIR]:
        os.makedirs(d, exist_ok=True)
        log(f"Ensured directory: {d}")
    
    progress = {
        "started_at": datetime.now().isoformat(),
        "notes": {"total": 0, "exported": 0, "failed": 0, "skipped": 0},
        "reminders": {"total": 0, "exported": 0, "failed": 0},
        "calendar": {"total": 0, "exported": 0, "failed": 0},
        "status": "running"
    }
    save_progress(progress)
    
    # =====================================================================
    # PHASE 1: Apple Notes
    # =====================================================================
    log("\n--- PHASE 1: Apple Notes ---")
    
    all_notes = get_all_note_metadata()
    # Skip "Recently Deleted" folder
    all_notes = [n for n in all_notes if n['folder'] != 'Recently Deleted']
    progress['notes']['total'] = len(all_notes)
    save_progress(progress)
    log(f"Found {len(all_notes)} notes (excluding Recently Deleted)")
    
    for i, note_meta in enumerate(all_notes):
        folder = note_meta['folder']
        note_id = note_meta['id']
        note_name = note_meta['name']
        
        log(f"\n[{i+1}/{len(all_notes)}] Processing: {note_name[:60]} ({folder})")
        
        # Fetch note body
        stdout, stderr, rc = fetch_note_body(note_id, timeout=20)
        
        if rc != 0 or stdout.startswith("ERROR:"):
            log(f"  FAILED to fetch: {stderr[:100] if stderr else stdout[:100]}")
            progress['notes']['failed'] += 1
            save_progress(progress)
            continue
        
        # Parse the note data
        lines = stdout.split('\n')
        created_str = ""
        modified_str = ""
        body_start_idx = -1
        for j, line in enumerate(lines):
            if line.startswith("NAME:"):
                note_name = line[5:]
            elif line.startswith("CREATED:"):
                created_str = line[8:]
            elif line.startswith("MODIFIED:"):
                modified_str = line[9:]
            elif line.startswith("===BODY==="):
                body_start_idx = j + 1
                break
        
        body_html = '\n'.join(lines[body_start_idx:]) if body_start_idx >= 0 else ""
        body_text = html_to_text(body_html)
        
        # Skip empty notes
        if len(body_text.strip()) < 10:
            log(f"  SKIPPED (empty or near-empty)")
            progress['notes']['skipped'] += 1
            save_progress(progress)
            continue
        
        # Enrich with Claude
        enrichment = enrich_with_claude(note_name, body_text, "note")
        
        if enrichment is None:
            # Fallback: basic metadata without Claude
            enrichment = {
                "title": note_name,
                "summary": "",
                "category": "archive" if folder == "90 Archive" else "personal",
                "action_items": [],
                "entities": [],
                "tags": [],
                "status": "archived" if folder == "90 Archive" else "active",
                "sensitive": bool(re.search(r'password|credential|ssh|login|recovery key|vault', body_text, re.IGNORECASE))
            }
            log(f"  Using fallback metadata (Claude enrichment failed)")
        
        # Build frontmatter
        apple_note_id = note_id.split('/')[-1] if '/' in note_id else note_id
        frontmatter = {
            "title": enrichment.get("title", note_name),
            "summary": enrichment.get("summary", ""),
            "category": enrichment.get("category", "personal"),
            "source_folder": folder,
            "tags": enrichment.get("tags", []),
            "action_items": enrichment.get("action_items", []),
            "entities": enrichment.get("entities", []),
            "status": enrichment.get("status", "active"),
            "sensitive": enrichment.get("sensitive", False),
            "exported_from": "apple_notes",
            "exported_date": datetime.now().isoformat(),
            "apple_note_id": apple_note_id,
            "apple_created": created_str,
            "apple_modified": modified_str,
        }
        
        # Write file
        filename = f"{sanitize_filename(enrichment.get('title', note_name))}.md"
        filepath = os.path.join(NOTES_DIR, filename)
        
        # Avoid overwriting if filename collides
        if os.path.exists(filepath):
            filepath = os.path.join(NOTES_DIR, f"{sanitize_filename(enrichment.get('title', note_name))}_{apple_note_id[-6:]}.md")
        
        size = write_enriched_markdown(filepath, frontmatter, body_text)
        log(f"  Written: {filename} ({size} bytes)")
        progress['notes']['exported'] += 1
        save_progress(progress)
    
    log(f"\nNotes phase complete: {progress['notes']['exported']} exported, {progress['notes']['skipped']} skipped, {progress['notes']['failed']} failed")
    
    # =====================================================================
    # PHASE 2: Apple Reminders
    # =====================================================================
    log("\n--- PHASE 2: Apple Reminders ---")
    
    all_reminders = get_all_reminders()
    progress['reminders']['total'] = len(all_reminders)
    save_progress(progress)
    log(f"Found {len(all_reminders)} reminders")
    
    for i, rem in enumerate(all_reminders):
        rem_name = rem.get("NAME", "Untitled")
        rem_list = rem.get("LIST", "Unknown")
        
        log(f"\n[{i+1}/{len(all_reminders)}] Processing: {rem_name[:60]} ({rem_list})")
        
        body = rem.get("BODY", "")
        due = rem.get("DUE", "none")
        completed = rem.get("COMPLETED", "false")
        priority = rem.get("PRIORITY", "0")
        created = rem.get("CREATED", "")
        
        # Enrich with Claude (shorter timeout for reminders - they're small)
        enrichment = enrich_with_claude(rem_name, f"Reminder: {rem_name}\nList: {rem_list}\nDue: {due}\nNotes: {body}", "reminder")
        
        if enrichment is None:
            enrichment = {
                "title": rem_name,
                "summary": "",
                "category": "personal",
                "action_items": [{"action": rem_name, "due": due, "completed": completed.lower() == "true"}],
                "entities": [],
                "tags": ["todo"],
                "status": "completed" if completed.lower() == "true" else "active",
                "sensitive": False
            }
        
        frontmatter = {
            "title": enrichment.get("title", rem_name),
            "summary": enrichment.get("summary", ""),
            "category": enrichment.get("category", "personal"),
            "source_list": rem_list,
            "tags": enrichment.get("tags", ["todo"]),
            "action_items": enrichment.get("action_items", []),
            "entities": enrichment.get("entities", []),
            "status": "completed" if completed.lower() == "true" else enrichment.get("status", "active"),
            "priority": int(priority) if priority.isdigit() else 0,
            "due_date": due if due != "none" else "",
            "completed": completed.lower() == "true",
            "sensitive": enrichment.get("sensitive", False),
            "exported_from": "apple_reminders",
            "exported_date": datetime.now().isoformat(),
            "apple_created": created,
        }
        
        filename = f"{sanitize_filename(rem_name)}.md"
        filepath = os.path.join(REMINDERS_DIR, filename)
        if os.path.exists(filepath):
            filepath = os.path.join(REMINDERS_DIR, f"{sanitize_filename(rem_name)}_{i}.md")
        
        body_text = f"# {rem_name}\n\n**List:** {rem_list}\n**Due:** {due}\n**Status:** {'Completed' if completed.lower() == 'true' else 'Pending'}\n\n{body}"
        size = write_enriched_markdown(filepath, frontmatter, body_text)
        log(f"  Written: {filename} ({size} bytes)")
        progress['reminders']['exported'] += 1
        save_progress(progress)
    
    log(f"\nReminders phase complete: {progress['reminders']['exported']} exported")
    
    # =====================================================================
    # PHASE 3: Apple Calendar
    # =====================================================================
    log("\n--- PHASE 3: Apple Calendar ---")
    
    all_events = get_calendar_events()
    progress['calendar']['total'] = len(all_events)
    save_progress(progress)
    log(f"Found {len(all_events)} calendar events")
    
    for i, evt in enumerate(all_events):
        evt_name = evt.get("NAME", "Untitled Event")
        evt_cal = evt.get("CAL", "Unknown")
        
        log(f"\n[{i+1}/{len(all_events)}] Processing: {evt_name[:60]} ({evt_cal})")
        
        start = evt.get("START", "")
        end = evt.get("END", "")
        location = evt.get("LOCATION", "none")
        notes = evt.get("NOTES", "none")
        all_day = evt.get("ALLDAY", "false")
        
        # Enrich with Claude
        enrichment = enrich_with_claude(evt_name, f"Event: {evt_name}\nCalendar: {evt_cal}\nStart: {start}\nEnd: {end}\nLocation: {location}\nNotes: {notes}", "calendar event")
        
        if enrichment is None:
            enrichment = {
                "title": evt_name,
                "summary": "",
                "category": "personal",
                "action_items": [],
                "entities": [],
                "tags": ["meeting"],
                "status": "active",
                "sensitive": False
            }
        
        frontmatter = {
            "title": enrichment.get("title", evt_name),
            "summary": enrichment.get("summary", ""),
            "category": enrichment.get("category", "personal"),
            "source_calendar": evt_cal,
            "tags": enrichment.get("tags", ["meeting"]),
            "action_items": enrichment.get("action_items", []),
            "entities": enrichment.get("entities", []),
            "status": enrichment.get("status", "active"),
            "start_date": start,
            "end_date": end,
            "all_day": all_day.lower() == "true",
            "location": location if location != "none" else "",
            "sensitive": enrichment.get("sensitive", False),
            "exported_from": "apple_calendar",
            "exported_date": datetime.now().isoformat(),
        }
        
        filename = f"{sanitize_filename(evt_name)}_{i}.md"
        filepath = os.path.join(CALENDAR_DIR, filename)
        
        body_text = f"# {evt_name}\n\n**Calendar:** {evt_cal}\n**Start:** {start}\n**End:** {end}\n**Location:** {location}\n\n{notes}"
        size = write_enriched_markdown(filepath, frontmatter, body_text)
        log(f"  Written: {filename} ({size} bytes)")
        progress['calendar']['exported'] += 1
        save_progress(progress)
    
    log(f"\nCalendar phase complete: {progress['calendar']['exported']} exported")
    
    # =====================================================================
    # Summary
    # =====================================================================
    progress['status'] = 'complete'
    progress['completed_at'] = datetime.now().isoformat()
    save_progress(progress)
    
    log("\n" + "=" * 60)
    log("Alexandria Apple Data Export — COMPLETE")
    log(f"  Notes:     {progress['notes']['exported']}/{progress['notes']['total']} exported, {progress['notes']['skipped']} skipped, {progress['notes']['failed']} failed")
    log(f"  Reminders: {progress['reminders']['exported']}/{progress['reminders']['total']} exported")
    log(f"  Calendar:  {progress['calendar']['exported']}/{progress['calendar']['total']} exported")
    log(f"  Output:    {SOURCES_DIR}")
    log(f"  Progress:  {PROGRESS_FILE}")
    log("=" * 60)

if __name__ == "__main__":
    main()