#!/usr/bin/env python3
"""Expand the managed containers without deleting their rollback predecessors.

Dry run by default. --deploy requires the user's private-workspace authorization.
Only explicit roots are mounted; no directory is created for a missing NAS.
Provider/profile/credential/grant configuration is not rewritten.
"""
from datetime import UTC, datetime
import argparse
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import time
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jaeger_ai.core.runtime import agent_workspaces as aw
from jaeger_ai.interfaces.hermes_profile_adapters.setup import _configure_webui_workspaces, _set_yaml_section_value

helpers = runpy.run_path(str(aw.REPO_ROOT/'scripts/setup-agent-workspaces.py'))
run, atomic_write = helpers['run'], helpers['atomic_write']
WATCHERS = ('com.jenkinsrobotics.agent-fabric-supervisor', 'com.jenkinsrobotics.hermes-native-api')


def ensure_idle(webui, openclaw):
    if webui.get('active_runs') != 0 or webui.get('active_streams') != 0:
        raise RuntimeError('WebUI has active or unknown work; postpone workspace maintenance')
    if (openclaw.get('tasks') or {}).get('active') != 0:
        raise RuntimeError('OpenClaw has active or unknown native work; postpone workspace maintenance')


def transition(plans, originals, *, invoke, verify, publish, restore):
    """Switch exact planned containers, with rollback on every failure path."""
    stopped, created = [], []
    try:
        for role, args in plans.items():
            stopped.append(role)
            invoke('stop', '--time', '15', originals[role])
            created.append(role)  # A failed create may still leave a stopped target.
            invoke(*args)
            invoke('start', aw.EXPANDED_CONTAINERS[role])
            verify(role, aw.EXPANDED_CONTAINERS[role])
        publish()
    except Exception as original:
        rollback_errors = []
        for role in reversed(created):
            try: invoke('stop', '--time', '10', aw.EXPANDED_CONTAINERS[role])
            except Exception: rollback_errors.append(f'stop replacement {role}')
        try: restore()
        except Exception: rollback_errors.append('restore configuration')
        for role in stopped:
            try: invoke('start', originals[role])
            except Exception: rollback_errors.append(f'start original {role}')
        if rollback_errors:
            raise RuntimeError('Workspace update failed; inspect rollback steps: '+', '.join(rollback_errors)) from None
        raise RuntimeError('Workspace update failed; original containers and configuration restored') from original


def access_probe(role, name, receipt_path):
    """Retain failure diagnostics privately before raising; never echo secrets."""
    command = [helpers['ENGINE'], 'exec', '--user', 'hermeswebui' if role == 'hermes' else 'node',
               name, '/app/venv/bin/python' if role == 'hermes' else 'python3',
               '/mnt/host/GitHub/JaegerAI/scripts/agent-mac-check.py', '--role', role,
               '--write-probe', '--all-workspaces']
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=45)
    except subprocess.TimeoutExpired:
        atomic_write(receipt_path, json.dumps({'error': 'timeout', 'role': role}))
        raise RuntimeError(f'{role} access probe timed out; private receipt retained') from None
    try:
        receipt = json.loads(result.stdout)
    except ValueError:
        receipt = {}
    atomic_write(receipt_path, json.dumps({'exit_code': result.returncode, 'receipt': receipt,
                                         'stdout': result.stdout, 'stderr': result.stderr}, indent=2))
    checks = receipt.get('checks', {})
    failed = [key for key, value in checks.items() if not value.get('ok')]
    if result.returncode or not checks or failed:
        raise RuntimeError(f'{role} access probe failed: {", ".join(failed) or "invalid probe result"}; private receipt retained')
    return receipt


def verify(role, name, receipt_path):
    deadline = time.monotonic()+60
    while True:
        if time.monotonic() >= deadline:
            raise RuntimeError(f'{role} replacement readiness timed out')
        try:
            status = json.loads(run('inspect', name, timeout=5))[0]['status']
            address = status['networks'][0]['ipv4Address'].split('/')[0]
            with urlopen(f'http://{address}:{8787 if role=="hermes" else 18789}/health', timeout=3) as response:
                if response.status == 200: break
        except Exception:
            pass
        time.sleep(.5)
    return access_probe(role, name, receipt_path)


def prepare():
    existing = set(run('list','--all','--quiet').splitlines())
    if existing.intersection(aw.EXPANDED_CONTAINERS.values()):
        raise RuntimeError('Expanded containers already exist; inspect before changing them')
    originals = {role:aw.container_name(role) for role in aw.MANAGED_CONTAINERS}
    if originals != aw.MANAGED_CONTAINERS:
        raise RuntimeError('Expansion requires the current managed deployment')
    configs = {role:json.loads(run('inspect',name))[0]['configuration'] for role,name in originals.items()}
    plans = {role:aw.create_arguments(config,role,include_personal=True,expand=True) for role,config in configs.items()}
    return originals, configs, plans


def deploy():
    originals, configs, plans = prepare()
    run('image','inspect',aw.HERMES_IMAGE)
    probe = ['run','--rm','--name','jaeger-expanded-mount-preflight','--entrypoint','/bin/true']
    for source,target in aw.workspace_mounts(include_personal=True): probe += ['--volume',f'{source}:{target}']
    run(*probe,aw.HERMES_IMAGE,timeout=30)
    with urlopen('http://100.74.2.15:8787/health',timeout=5) as response: health=json.load(response)
    from jaeger_ai.interfaces.hermes_profile_adapters.openclaw_native import NativeGateway
    from jaeger_ai.interfaces.hermes_profile_adapters.openclaw import OPENCLAW_BASE_URL,OPENCLAW_TOKEN_FILE
    with NativeGateway(OPENCLAW_BASE_URL,OPENCLAW_TOKEN_FILE) as gateway:
        native_status=gateway.request('status',{})
    ensure_idle(health,native_status)
    stamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
    backup = aw.STATE_PATH.parent/f'workspace-expansion-{stamp}'
    backup.mkdir(mode=0o700)
    atomic_write(backup/'containers.json',json.dumps(configs))
    home = Path.home()
    native_config = aw.REPO_ROOT/'.jaeger_ai/instances/jaeger/config.yaml'
    paths = [aw.STATE_PATH,native_config,home/'.hermes/workspaces.json']
    paths += [home/f'.hermes/profiles/{name}/webui_state/workspaces.json' for name in ('jaeger','openclaw','roundtable')]
    saved = []
    for index,path in enumerate(paths):
        if path.is_symlink(): raise RuntimeError('Refusing to replace a symlinked configuration during expansion')
        destination = backup/f'config-{index}'
        mode = path.stat().st_mode & 0o777 if path.exists() else None
        if mode is not None:
            shutil.copy2(path,destination); destination.chmod(0o600)
        saved.append((path,destination,mode))
    atomic_write(backup/'file-index.json',json.dumps([{'path':str(p),'backup':str(b),'mode':m} for p,b,m in saved]))
    def restore():
        for path,snapshot,mode in saved:
            if mode is None: path.unlink(missing_ok=True)
            else:
                atomic_write(path,snapshot.read_text()); path.chmod(mode)
    def publish():
        state=json.loads(aw.STATE_PATH.read_text())
        state.update(containers=aw.EXPANDED_CONTAINERS,rollback_containers=originals,backup=str(backup),
                     mounted_workspaces=[target for _,target in aw.workspace_mounts(include_personal=True)])
        atomic_write(aw.STATE_PATH,json.dumps(state,indent=2))
        _set_yaml_section_value(native_config,'containers','hermes_webui_container',aw.EXPANDED_CONTAINERS['hermes'])
        _configure_webui_workspaces(home)
    receipts = {}
    def verify_and_record(role,name): receipts[role]=verify(role,name,backup/f'{role}-probe.json')
    domain=f'gui/{os.getuid()}'
    paused=[]
    try:
        for label in WATCHERS:
            if subprocess.run(['/bin/launchctl','list',label],capture_output=True,timeout=5).returncode==0:
                subprocess.run(['/bin/launchctl','bootout',f'{domain}/{label}'],check=True,capture_output=True,timeout=15)
                paused.append(label)
        transition(plans,originals,invoke=run,verify=verify_and_record,publish=publish,restore=restore)
        atomic_write(backup/'verification.json',json.dumps(receipts,indent=2))
        print(f'Workspace expansion verified; originals retained stopped. Private receipts: {backup}')
    finally:
        failed=[]
        for label in reversed(paused):
            plist=home/'Library/LaunchAgents'/(label+'.plist')
            result=subprocess.run(['/bin/launchctl','bootstrap',domain,str(plist)],capture_output=True,timeout=15)
            if result.returncode: failed.append(label)
        if failed: raise RuntimeError('Restore monitoring before continuing: '+', '.join(failed))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deploy',action='store_true')
    args=parser.parse_args()
    if args.deploy: deploy()
    else:
        originals,_,_=prepare()
        print(json.dumps({'originals_retained':originals,'replacements':aw.EXPANDED_CONTAINERS,
                          'workspaces':[str(source) for source,_ in aw.workspace_mounts(include_personal=True)]},indent=2))
