#!/usr/bin/env python3
"""Read Safari bookmarks directly from the plist file."""
import plistlib
import json
from pathlib import Path

bm_path = Path.home() / 'Library/Safari/Bookmarks.plist'
print(f"Reading: {bm_path}", flush=True)

with open(bm_path, 'rb') as f:
    data = plistlib.load(f)

def extract_bookmarks(node, folder_path=""):
    results = []
    if not isinstance(node, dict):
        return results
    title = node.get('Title', '')
    current_path = f"{folder_path}/{title}" if folder_path else title
    bm_type = node.get('WebBookmarkType', '')
    if bm_type == 'WebBookmarkTypeLeaf':
        results.append({
            'title': title,
            'url': node.get('URLString', ''),
            'folder': folder_path,
        })
    elif bm_type == 'WebBookmarkTypeList':
        for child in node.get('Children', []):
            results.extend(extract_bookmarks(child, current_path))
    return results

bookmarks = []
for child in data.get('Children', []):
    bookmarks.extend(extract_bookmarks(child))

# Also extract reading list
reading_list = []
for child in data.get('Children', []):
    if isinstance(child, dict) and child.get('Title') == 'com.apple.ReadingList':
        for item in child.get('Children', []):
            if item.get('WebBookmarkType') == 'WebBookmarkTypeLeaf':
                rl_info = item.get('ReadingList', {})
                reading_list.append({
                    'title': item.get('Title', ''),
                    'url': item.get('URLString', ''),
                    'date_added': str(rl_info.get('DateAdded', '')),
                    'preview': str(rl_info.get('Preview', ''))[:200],
                })

print(f"\nTotal bookmarks: {len(bookmarks)}", flush=True)
print(f"Reading list items: {len(reading_list)}", flush=True)

# Show folder structure
folders = {}
for b in bookmarks:
    folder = b['folder'] or '(root)'
    if folder not in folders:
        folders[folder] = 0
    folders[folder] += 1

print(f"\nFolders ({len(folders)}):", flush=True)
for folder, count in sorted(folders.items(), key=lambda x: -x[1])[:20]:
    print(f"  {count:4d}  {folder}", flush=True)

print(f"\nFirst 30 bookmarks:", flush=True)
for b in bookmarks[:30]:
    print(f"  [{b['folder'][:30]}] {b['title'][:50]}: {b['url'][:70]}", flush=True)

if reading_list:
    print(f"\nReading list:", flush=True)
    for r in reading_list[:10]:
        print(f"  {r['title'][:50]}: {r['url'][:70]}", flush=True)

# Save full index
output = {
    'bookmarks': bookmarks,
    'reading_list': reading_list,
    'folder_summary': folders,
}
out_path = Path.home() / 'workspace' / 'hermes-work' / 'safari-index.json'
with open(out_path, 'w') as f:
    json.dump(output, f, indent=2, ensure_ascii=False)
print(f"\nSaved to: {out_path} ({out_path.stat().st_size} bytes)", flush=True)