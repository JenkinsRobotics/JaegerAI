"""Build an owned browser bundle outside the source tree (macOS arm64).

Source, Node and Chromium versions are pinned. Nothing is downloaded at runtime.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

STEEL = "c8aebf9462187fc5a80b587ba2086900aecab236"
NODE = "22.23.2"
NODE_SHA = "5eff7a9011895aae3f29d06f167b84a62b028a591370c7cafb59103559fd26e1"


def run(*args, cwd=None, env=None):
    subprocess.run(args, cwd=cwd, env=env, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steel-source", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    repo = Path(__file__).resolve().parents[2]
    if output == repo or repo in output.parents:
        raise SystemExit("Browser bundles must be built outside the repository")
    if output.exists():
        raise SystemExit("Output already exists; choose a new candidate directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="jaeger-browser-build-", dir=output.parent) as temp:
        stage = Path(temp)
        archive = stage / "node.tar.xz"
        urllib.request.urlretrieve(f"https://nodejs.org/dist/v{NODE}/node-v{NODE}-darwin-arm64.tar.xz", archive)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != NODE_SHA:
            raise SystemExit("Node checksum mismatch")
        with tarfile.open(archive) as tar:
            tar.extractall(stage, filter="data")
        node_root = stage / f"node-v{NODE}-darwin-arm64"
        bundle = stage / "bundle"
        bundle.mkdir()
        shutil.copytree(node_root, bundle / "node", symlinks=True)
        env = {**os.environ, "PATH": str(bundle / "node/bin") + os.pathsep + os.environ["PATH"]}
        steel = bundle / "steel"
        if args.steel_source:
            source = args.steel_source.resolve()
            actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
            if actual != STEEL:
                raise SystemExit("Steel checkout revision mismatch")
            run("git", "diff", "--exit-code", "HEAD", cwd=source)
            shutil.copytree(source, steel, symlinks=True, ignore=shutil.ignore_patterns(".git", "node_modules", "build", "dist"))
        else:
            run("git", "clone", "--no-checkout", "https://github.com/steel-dev/steel-browser.git", str(steel))
            run("git", "checkout", "--detach", STEEL, cwd=steel)
            shutil.rmtree(steel / ".git")
        run("npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund", cwd=steel, env=env)
        run("npm", "rebuild", "duckdb", cwd=steel, env=env)
        # Bounded portability patch: upstream production assumes Docker's /files.
        storage = steel / "api/src/services/file.service.ts"
        original = storage.read_text()
        before = '      options.baseFilesPath ??'
        if original.count(before) != 1:
            raise SystemExit("Steel file-storage patch no longer applies")
        original = original.replace(before, before + '\n      process.env.JAEGER_BROWSER_FILES ??')
        before = 'options.prebuiltArchiveDir ?? "/tmp/.steel"'
        if original.count(before) != 1:
            raise SystemExit("Steel archive patch no longer applies")
        storage.write_text(original.replace(before, 'options.prebuiltArchiveDir ?? process.env.JAEGER_BROWSER_ARCHIVES ?? "/tmp/.steel"'))
        cast = steel / "api/src/plugins/browser-socket/casting.handler.ts"
        before = '        browserWSEndpoint: `ws://${env.HOST}:${env.PORT}`,'
        original = cast.read_text()
        if original.count(before) != 1:
            raise SystemExit("Steel private cast connection patch no longer applies")
        cast.write_text(original.replace(before, before + '\n        defaultViewport: null,\n        headers: process.env.JAEGER_BROWSER_TOKEN ? { Authorization: `Bearer ${process.env.JAEGER_BROWSER_TOKEN}` } : {},'))
        browser = steel / "api/src/plugins/browser.ts"
        before = '    await cdpService.launch();'
        original = browser.read_text()
        if original.count(before) != 1:
            raise SystemExit("Steel duplicate launch patch no longer applies")
        browser.write_text(original.replace(before, '    if (!cdpService.getBrowserInstance()) await cdpService.launch();'))
        # Viewing must never resize the page owned by the conversation worker.
        screencast = steel / "api/src/plugins/browser-socket/page-screencast.ts"
        original = screencast.read_text()
        start = original.index("    const { width, height, isMobile } = this.viewport;")
        end = original.index('    client.on("Page.screencastFrame"', start)
        screencast.write_text(original[:start] + original[end:])
        run("npm", "run", "build", "--workspace", "api", cwd=steel, env=env)
        ui = repo / "jaeger_ai/interfaces/ui"
        # The canonical UI lockfile pins Playwright and its Chromium revision.
        playwright = ui / "node_modules/playwright-core"
        browser_spec = next(x for x in json.loads((playwright / "browsers.json").read_text())["browsers"] if x["name"] == "chromium")
        cache = stage / "chromium-cache"
        run(str(bundle / "node/bin/node"), str(playwright / "cli.js"), "install", "chromium", "--no-shell", env={**env, "PLAYWRIGHT_BROWSERS_PATH": str(cache)})
        chromium = cache / ("chromium-" + browser_spec["revision"])
        shutil.copytree(chromium, bundle / "chromium", symlinks=True)
        chrome = "chromium/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
        if not (bundle / chrome).is_file():
            raise SystemExit("Unexpected Chromium archive layout")
        shutil.copy2(Path(__file__).with_name("worker.mjs"), bundle / "worker.mjs")
        manifest = {"steel_commit": STEEL, "steel_patches": ["conversation-file-storage", "authenticated-cast", "single-launch", "retain-page-viewport"], "node_version": NODE, "node_archive_sha256": NODE_SHA,
                    "chromium": browser_spec, "node": "node/bin/node", "chrome": chrome}
        (bundle / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        run(str(bundle / "node/bin/node"), "--check", str(bundle / "worker.mjs"))
        bundle.rename(output)
    print(output)


if __name__ == "__main__":
    main()
