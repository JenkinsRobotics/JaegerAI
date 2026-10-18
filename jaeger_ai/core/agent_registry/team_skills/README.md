# Team role skills

One SKILL.md folder per team role. `scripts/install-team-skills.sh <skills_dir>`
copies them into an instance's `skills/` directory (with the REA skill folder,
whole, when its source is given). `specialists.py` names which skills each role
loads; a specialist run only sees its own skills plus the shared handbook.
