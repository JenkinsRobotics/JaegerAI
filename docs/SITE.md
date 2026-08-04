# Deploying this site (the standard for ALL Jaeger repos)

GitHub → Settings → Pages → Source: **Deploy from a branch** →
Branch: `master`, Folder: **`/docs`** → Save. Live in ~1 minute at
`https://jenkinsrobotics.github.io/<repo>/`.

(The main JROS site uses the older gh-pages-branch method; module repos
standardize on the /docs folder — site ships atomically with code.)

# docs/ — the repo's GitHub Pages site

`index.html` is cloned from [JROS-site](https://github.com/JenkinsRobotics/JROS)'s
own marketing page — same CSS design system (palette, nav, hero,
feature-grid, architecture boxes, roadmap timeline, footer, the
IntersectionObserver scroll-reveal script), parameterized with
`{{PLACEHOLDER}}` markers instead of JROS's real content. Every asset is
either inline (all CSS/JS) or a stable external link the original JROS
site also uses (the Jenkins Robotics logo) — nothing to bundle.

## Enable GitHub Pages

1. Push this repo with `docs/index.html` in place.
2. On GitHub: **Settings → Pages → Build and deployment → Source:**
   `Deploy from a branch`.
3. **Branch:** your default branch, **folder:** `/gh-pages` (GitHub only
   offers `/` or `/docs` in the folder dropdown for a non-`docs`-named
   branch — if `/gh-pages` isn't selectable, either rename this directory
   to `docs/` or push its contents to a dedicated `docs` branch at the
   repo root instead).
4. Save. The site publishes at `https://JenkinsRobotics.github.io/{{REPO_NAME}}/`.

## Customize

Fill in every `{{PLACEHOLDER}}` in `index.html` — same markers as
`README.md`, plus site-specific ones:

| Placeholder | What it is |
|---|---|
| `{{REPO_NAME}}` | Repo name — nav brand, hero wordmark, all GitHub links |
| `{{DESCRIPTION}}` | One-line description — meta tags, hero lede, "what it is" |
| `{{TAGLINE}}` | Short `// slogan`-style line under the hero logo |
| `{{STATUS_LINE}}` | The pill badge text, e.g. `Latest release: 0.1.0` |
| `{{HERO_HEADLINE_PLAIN}}` / `{{HERO_HEADLINE_ACCENT}}` | The big H1, split so the accent span gets the gradient treatment (mirrors JROS's "Where the agent **meets the metal**") |
| `{{WHAT_HEADLINE}}` / `{{CAPABILITIES_HEADLINE}}` / `{{ROADMAP_HEADLINE}}` | Section headlines |
| `{{FEATURE_N_*}}` | Feature-grid cards — delete/duplicate the `<div class="feature">` blocks to match however many real capabilities this repo has; keep the `feature dev` (dashed) variant for anything still `(planned)` |
| `{{MILESTONE_N_*}}` | Roadmap timeline entries — `milestone done` / `milestone next` / plain (future) classes control the dot styling |

Keep the CSS variables in `:root` untouched unless this repo deliberately
wants a different accent color from the rest of the ecosystem — the
point of cloning the design system is that every Jaeger repo's page
looks like a family member, not a one-off.

## What's different from the JROS site

The original has extra sections (Mind·Body·Soul pillars, a positioning
table vs. ROS/Hermes, a detailed multi-step install flow) that are
JaegerOS-specific framing, not generic template content — they're not
reproduced here. Add them back into `index.html` (copy the section
markup + its scoped `<style>` block from
[JROS-site/index.html](https://github.com/JenkinsRobotics/JROS)) if a
given repo wants that level of detail.
