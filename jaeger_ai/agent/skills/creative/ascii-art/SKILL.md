---
name: ascii-art
description: "Make ASCII/Unicode text art — banners (pyfiglet/toilet), speech-bubble critters (cowsay), decorative borders (boxes), image-to-ASCII, and curated art from the web. Load this when the user wants a text banner, logo, terminal art, or an image converted to ASCII."
version: 4.1.0
platforms: [macos, linux, windows]
requires_tools: [terminal]
metadata:
  jros:
    tags: [ascii, art, banner, figlet, cowsay, unicode]
    category: creative
    related_skills: [excalidraw]
---

# ASCII ART

Every generator here is a local CLI or a free REST API. Run them all through the
`terminal` tool — no API keys. Pick the tool from DECISION FLOW, run it, show the output.

## DECISION FLOW (pick one, then run it)

1. Text banner → `pyfiglet` if installed, else the `asciified` API (curl).
2. Message in a critter's speech bubble → `cowsay`.
3. Decorative border/frame → `boxes` (pipe a banner into it).
4. Colored/filtered banner → `toilet` (ANSI color; may not render outside a terminal).
5. Art of a specific thing (cat, rocket, dragon) → fetch from `ascii.co.uk` (curl + parse).
6. Convert an image to ASCII → `ascii-image-converter` or `jp2a`.
7. QR code / weather art → `qrenco.de` / `wttr.in` (curl).
8. Nothing above fits → hand-build from the UNICODE PALETTE below.
9. A tool isn't installed → install it, or drop to the next option.

## 1. TEXT BANNERS — pyfiglet (local, 571 fonts)

```bash
pip install pyfiglet --break-system-packages -q     # once
python3 -m pyfiglet "YOUR TEXT" -f slant
python3 -m pyfiglet "TEXT" -f doom -w 80            # -w sets width
python3 -m pyfiglet --list_fonts                    # all fonts
```
Good fonts: `slant` (clean), `doom`/`big` (bold), `small`/`mini` (long text),
`banner3`/`cyberlarge` (wide). Short text suits detailed fonts; long text suits compact ones.

## 2. TEXT BANNERS — asciified API (remote, no install)

Returns plain-text art directly. Use when pyfiglet isn't installed. Encode spaces as `+`.

```bash
curl -s "https://asciified.thelicato.io/api/v2/ascii?text=Hello+World"
curl -s "https://asciified.thelicato.io/api/v2/ascii?text=Hello&font=Slant"
curl -s "https://asciified.thelicato.io/api/v2/fonts"        # list font names (case-sensitive)
```

## 3. COWSAY (message in a speech bubble)

```bash
sudo apt install cowsay -y      # or: brew install cowsay
cowsay "Hello World"
cowsay -f tux "Linux rules"     # -f picks the character; cowsay -l lists them
cowthink "Hmm..."               # thought bubble
```
Characters incl. `tux dragon stegosaurus elephant skull vader turtle sheep ghostbusters`.
Eye modifiers: `-b` borg, `-d` dead, `-g` greedy, `-p` paranoid, `-s` stoned, `-e "OO"` custom.

## 4. BOXES (decorative borders)

```bash
sudo apt install boxes -y       # or: brew install boxes
echo "Hello World" | boxes -d stone
boxes -l                        # list 70+ designs (stone parchment cat dog diamonds c-cmt …)
python3 -m pyfiglet "JROS" -f slant | boxes -d stone     # combine with a banner
```

## 5. TOILET (colored banners)

```bash
sudo apt install toilet toilet-fonts -y     # or: brew install toilet
toilet -f pagga "Block"        # unique block font
toilet --gay "Rainbow!"        # also --metal, -F border
toilet -F list                 # list filters
```
Outputs ANSI color codes — great in a terminal, may not render in plain text/chat.

## 6. IMAGE → ASCII

```bash
# ascii-image-converter (recommended): snap install ascii-image-converter
ascii-image-converter image.png            # -C color, -b braille, -d 60,30 dims, URL ok
# jp2a (lightweight, JPEG only): sudo apt install jp2a -y
jp2a --width=80 --colors image.jpg
```

## 7. CURATED ART — ascii.co.uk

Pattern `https://ascii.co.uk/art/{subject}` (subjects: cat dog dragon rocket skull robot
tree star christmas …). Art lives in HTML `<pre>` tags. Fetch, then extract:

```bash
curl -s 'https://ascii.co.uk/art/cat' -o /tmp/ascii_art.html
python3 -c "
import re, html
t = open('/tmp/ascii_art.html').read()
for a in re.findall(r'<pre[^>]*>(.*?)</pre>', t, re.DOTALL):
    c = html.unescape(re.sub(r'<[^>]+>', '', a)).strip()
    if len(c) > 30: print(c, '\n---\n')
"
```
Preserve any artist signature/initials — that's etiquette. Pick the best piece for the user.

## 8. FUN EXTRAS (curl)

```bash
curl -s "qrenco.de/Hello+World"     # QR code as ASCII
curl -s "wttr.in/London"            # weather art;  wttr.in/Moon for moon phase
curl -s https://api.github.com/octocat   # random Octocat + quote
```

## 9. HAND-BUILT (fallback)

No tool fits → compose from these. Max 60 wide, ≤15 lines (banner)/25 (scene), monospace only.
Box `╔ ╗ ╚ ╝ ║ ═ ┌ ┐ └ ┘ │ ─ ├ ┤ ┼ ╭ ╮ ╰ ╯` · Blocks `░ ▒ ▓ █ ▄ ▀ ▌ ▐` · Symbols `◆ ● ○ ■ □ ▲ ▼ ★ ☆ ✦ ◀ ▶ ⬡ ⬢`

## ERROR HATCH

A CLI tool is missing → install it (`pip`/`apt`/`brew`), or fall to the next option in
DECISION FLOW. If a curl endpoint fails twice, switch to a local tool (pyfiglet/hand-built).

## DONE WHEN

The requested art is generated and shown to the user in a monospace-safe block. If it was
saved, report the file path (`--save-txt` for images, or `write_file` for captured output).
