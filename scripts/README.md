# scripts/ — the frozen curl-install target

This directory holds exactly one thing: **`install.sh`**, the script the public
one-line installer pipes into bash.

```bash
curl -fsSL https://raw.githubusercontent.com/JenkinsRobotics/JROS/master/scripts/install.sh | bash
```

## Do not move or rename `scripts/install.sh`

That raw URL is **baked into documentation, the README, and existing operator
muscle memory**. The path `scripts/install.sh` on the `master` branch is a
public contract — moving or renaming it is a breaking change that 404s every
copy of the install command in the wild. It stays here, with this name, forever.

What `scripts/install.sh` does: detect Python 3.11/3.12, clone the repo into the
install root (`$JAEGER_HOME`, default `~/jaeger`), copy the product allowlist,
and run the in-repo `./install.sh` (which makes the `.venv` and does
`uv pip install -e .`). It never touches `.venv/` or `.jaeger_os/` on a re-run.

## Not to be confused with…

- **`/install.sh`** (repo root) — the *local* installer the curl script calls
  once the repo is on disk; it builds the venv + editable-installs JROS. Run it
  yourself after a manual `git clone`.
- **`dev/scripts/`** — internal developer tooling (`dev_env.sh`,
  `run_tests.sh`, generators). Never shipped to an end-user install, free to
  move/rename.
