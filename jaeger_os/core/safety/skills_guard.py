"""Skill safety guard — a static content scanner for skills.

A skill is executable-by-proxy: a playbook SKILL.md is markdown the
agent is told to run via `terminal` / `execute_code`, and a code skill
is Python the loader imports. Nothing else scans that content. This
module is the scan — a dependency-free regex pass over skill files for
exfiltration, prompt injection, destructive commands, persistence,
reverse shells, obfuscation, and embedded secrets.

Ported from hermes-agent's ``skills_guard.py`` (the threat-pattern
corpus) and trimmed to JROS's needs.

Call sites:
  • ``skill_loader`` scans a code skill's files before importing it.
  • the ``skill`` tool scans a playbook before handing it to the model.

Verdict: ``danger`` (a critical finding), ``caution`` (a high finding),
or ``clean``. The loader skips a ``danger`` skill; the ``skill`` tool
surfaces a warning.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# (regex, id, severity, category, description). severity is one of
# "critical" | "high" | "medium" | "low".
_RAW_PATTERNS: list[tuple[str, str, str, str, str]] = [
    # ── Exfiltration ──
    # curl/wget carrying a secret is "high" not "critical": the regex
    # can't see the destination, and a legit API skill curls its own
    # service with a token. Worth a caution, not an outright block.
    (r'curl\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)',
     "env_exfil_curl", "high", "exfiltration",
     "curl interpolating a secret environment variable"),
    (r'wget\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)',
     "env_exfil_wget", "high", "exfiltration",
     "wget interpolating a secret environment variable"),
    (r'requests\.(get|post|put|patch)\s*\([^\n]*(KEY|TOKEN|SECRET|PASSWORD)',
     "env_exfil_requests", "critical", "exfiltration",
     "HTTP request carrying a secret variable"),
    (r'\~/\.ssh|\$HOME/\.ssh', "ssh_dir_access", "high", "exfiltration",
     "references the user's SSH directory"),
    (r'\~/\.aws|\$HOME/\.aws', "aws_dir_access", "high", "exfiltration",
     "references the user's AWS credentials directory"),
    (r'\~/\.gnupg|\$HOME/\.gnupg', "gpg_dir_access", "high", "exfiltration",
     "references the user's GPG keyring"),
    (r'\~/\.jaeger/.*\.env|\.jaeger/credentials',
     "jaeger_secrets_access", "critical", "exfiltration",
     "directly references the Jaeger secrets store"),
    (r'cat\s+[^\n]*(\.env|credentials|\.netrc|\.pgpass|\.npmrc|\.pypirc)',
     "read_secrets_file", "critical", "exfiltration",
     "reads a known secrets file"),
    (r'printenv|env\s*\|', "dump_all_env", "high", "exfiltration",
     "dumps all environment variables"),
    (r'os\.getenv\s*\(\s*[^\)]*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)',
     "python_getenv_secret", "critical", "exfiltration",
     "reads a secret via os.getenv()"),
    (r'\b(dig|nslookup|host)\s+[^\n]*\$', "dns_exfil", "critical",
     "exfiltration", "DNS lookup with interpolation (DNS exfiltration)"),
    (r'!\[.*\]\(https?://[^\)]*\$\{?', "md_image_exfil", "high",
     "exfiltration", "markdown image URL with variable interpolation"),
    (r'(include|output|print|send|share)\s+(?:\w+\s+)*'
     r'(conversation|chat\s+history|previous\s+messages|context)',
     "context_exfil", "high", "exfiltration",
     "instruction to leak the conversation context"),
    # ── Prompt injection ──
    (r'ignore\s+(?:\w+\s+)*(previous|all|above|prior)\s+instructions',
     "prompt_injection_ignore", "critical", "injection",
     "prompt injection: ignore previous instructions"),
    (r'do\s+not\s+(?:\w+\s+)*tell\s+(?:\w+\s+)*the\s+user',
     "deception_hide", "critical", "injection",
     "instructs the agent to hide information from the user"),
    (r'system\s+prompt\s+override', "sys_prompt_override", "critical",
     "injection", "attempts to override the system prompt"),
    (r'disregard\s+(?:\w+\s+)*(your|all|any)\s+(?:\w+\s+)*'
     r'(instructions|rules|guidelines)',
     "disregard_rules", "critical", "injection",
     "instructs the agent to disregard its rules"),
    (r'(when|if)\s+no\s*one\s+is\s+(watching|looking)',
     "conditional_deception", "high", "injection",
     "conditional instruction to misbehave when unobserved"),
    (r'<!--[^>]*(ignore|override|system|secret|hidden)[^>]*-->',
     "html_comment_injection", "high", "injection",
     "hidden instructions in an HTML comment"),
    (r'\bDAN\s+mode\b|Do\s+Anything\s+Now', "jailbreak_dan", "critical",
     "injection", "DAN jailbreak attempt"),
    (r'(respond|answer|reply)\s+without\s+(?:\w+\s+)*'
     r'(restrictions|limitations|filters|safety)',
     "remove_filters", "critical", "injection",
     "instructs the agent to drop its safety filters"),
    # ── Destructive ──
    (r'rm\s+-rf\s+/', "destructive_root_rm", "critical", "destructive",
     "recursive delete from root"),
    (r'rm\s+(-[^\s]*)?r.*\$HOME', "destructive_home_rm", "critical",
     "destructive", "recursive delete targeting the home directory"),
    (r'>\s*/etc/', "system_overwrite", "critical", "destructive",
     "overwrites a system configuration file"),
    (r'\bmkfs\b', "format_filesystem", "critical", "destructive",
     "formats a filesystem"),
    (r'\bdd\s+.*if=.*of=/dev/', "disk_overwrite", "critical",
     "destructive", "raw disk write"),
    (r'shutil\.rmtree\s*\(\s*[\"\'/]', "python_rmtree", "high",
     "destructive", "rmtree on an absolute / root path"),
    # ── Persistence ──
    (r'authorized_keys', "ssh_backdoor", "critical", "persistence",
     "modifies SSH authorized_keys"),
    (r'\bcrontab\b', "persistence_cron", "medium", "persistence",
     "modifies cron jobs"),
    (r'\.(bashrc|zshrc|profile|bash_profile|zprofile)\b',
     "shell_rc_mod", "medium", "persistence",
     "references a shell startup file"),
    (r'launchctl\s+load|LaunchAgents|LaunchDaemons',
     "macos_launchd", "medium", "persistence",
     "macOS launch agent/daemon persistence"),
    (r'/etc/sudoers|visudo', "sudoers_mod", "critical", "persistence",
     "modifies sudoers (privilege escalation)"),
    # A mention of an agent-config file is "medium": discussing
    # CLAUDE.md isn't modifying it. A real persistence attempt would
    # also trip a write/echo pattern, which escalates the verdict.
    (r'AGENTS\.md|CLAUDE\.md|\.cursorrules|agent_system_prompt',
     "agent_config_mod", "medium", "persistence",
     "references agent-config files — could persist instructions"),
    # ── Network / reverse shells ──
    (r'\bnc\s+-[lp]|ncat\s+-[lp]|\bsocat\b', "reverse_shell", "critical",
     "network", "potential reverse-shell listener"),
    (r'/bin/(ba)?sh\s+-i\s+.*>/dev/tcp/', "bash_reverse_shell",
     "critical", "network", "bash reverse shell via /dev/tcp"),
    (r'python[23]?\s+-c\s+["\']import\s+socket',
     "python_socket_oneliner", "critical", "network",
     "Python socket one-liner (likely reverse shell)"),
    (r'\bngrok\b|\bcloudflared\b|\bserveo\b', "tunnel_service", "high",
     "network", "uses a tunneling service for external access"),
    (r'webhook\.site|requestbin|pipedream\.net|hookbin',
     "exfil_service", "high", "network",
     "references a known data-exfiltration / webhook service"),
    # ── Obfuscation ──
    (r'base64\s+(-d|--decode)\s*\|', "base64_decode_pipe", "high",
     "obfuscation", "base64-decodes and pipes to execution"),
    (r'echo\s+[^\n]*\|\s*(bash|sh|python|perl|ruby|node)',
     "echo_pipe_exec", "critical", "obfuscation",
     "echo piped into an interpreter"),
    (r'\beval\s*\(\s*["\']', "eval_string", "high", "obfuscation",
     "eval() on a string"),
    (r'\bexec\s*\(\s*["\']', "exec_string", "high", "obfuscation",
     "exec() on a string"),
    (r'__import__\s*\(\s*["\']os["\']\s*\)', "python_import_os", "high",
     "obfuscation", "dynamic import of the os module"),
    # ── Execution ──
    (r'os\.system\s*\(', "python_os_system", "high", "execution",
     "os.system() — unguarded shell execution"),
    (r'os\.popen\s*\(', "python_os_popen", "high", "execution",
     "os.popen() — shell pipe execution"),
    # ── Traversal ──
    (r'/etc/passwd|/etc/shadow', "system_passwd_access", "critical",
     "traversal", "references system password files"),
    (r'\.\./\.\./\.\.', "path_traversal_deep", "high", "traversal",
     "deep relative path traversal"),
    # ── Supply chain ──
    (r'curl\s+[^\n]*\|\s*(ba)?sh', "curl_pipe_shell", "critical",
     "supply_chain", "curl piped to a shell (download-and-execute)"),
    (r'curl\s+[^\n]*\|\s*python', "curl_pipe_python", "critical",
     "supply_chain", "curl piped to Python"),
    # ── Privilege escalation ──
    (r'\bsudo\b', "sudo_usage", "high", "privilege_escalation",
     "uses sudo"),
    (r'NOPASSWD', "nopasswd_sudo", "critical", "privilege_escalation",
     "NOPASSWD sudoers entry"),
    (r'setuid|setgid|chmod\s+[u+]?s', "suid_bit", "critical",
     "privilege_escalation", "sets a SUID/SGID bit"),
    # ── Crypto mining ──
    (r'xmrig|stratum\+tcp|cryptonight|coinhive', "crypto_mining",
     "critical", "mining", "cryptocurrency-mining reference"),
    # ── Embedded secrets ──
    (r'-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----', "embedded_private_key",
     "critical", "credential_exposure", "an embedded private key"),
    (r'ghp_[A-Za-z0-9]{36}', "github_token_leaked", "critical",
     "credential_exposure", "a GitHub token in the skill content"),
    (r'sk-ant-[A-Za-z0-9_-]{90,}', "anthropic_key_leaked", "critical",
     "credential_exposure", "an Anthropic API key in the skill content"),
    (r'AKIA[0-9A-Z]{16}', "aws_key_leaked", "critical",
     "credential_exposure", "an AWS access key in the skill content"),
]

# Compiled once. (compiled, id, severity, category, description).
_PATTERNS: list[tuple[re.Pattern[str], str, str, str, str]] = [
    (re.compile(rx, re.IGNORECASE), pid, sev, cat, desc)
    for rx, pid, sev, cat, desc in _RAW_PATTERNS
]

# Files worth scanning — text the agent could be told to run.
_SCANNABLE = {".md", ".py", ".sh", ".bash", ".zsh", ".js", ".ts",
              ".rb", ".pl", ".txt", ".yaml", ".yml", ".toml", ".json"}

_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


@dataclass
class Finding:
    """One pattern hit in a skill file."""
    pattern_id: str
    severity: str
    category: str
    description: str
    file: str
    line: int
    excerpt: str


@dataclass
class ScanResult:
    """The outcome of scanning a skill."""
    skill: str
    verdict: str               # "clean" | "caution" | "danger"
    findings: list[Finding] = field(default_factory=list)
    files_scanned: int = 0

    @property
    def is_clean(self) -> bool:
        return self.verdict == "clean"

    @property
    def is_danger(self) -> bool:
        return self.verdict == "danger"


def _verdict(findings: list[Finding]) -> str:
    severities = {f.severity for f in findings}
    if "critical" in severities:
        return "danger"
    if "high" in severities:
        return "caution"
    return "clean"


def scan_text(text: str, *, file: str = "") -> list[Finding]:
    """Scan a blob of text for threat patterns. Returns every finding."""
    findings: list[Finding] = []
    lines = text.splitlines()
    for compiled, pid, sev, cat, desc in _PATTERNS:
        for m in compiled.finditer(text):
            line_no = text.count("\n", 0, m.start()) + 1
            excerpt = ""
            if 1 <= line_no <= len(lines):
                excerpt = lines[line_no - 1].strip()[:160]
            findings.append(Finding(
                pattern_id=pid, severity=sev, category=cat,
                description=desc, file=file, line=line_no,
                excerpt=excerpt,
            ))
    return findings


def scan_skill(skill_path: Path, *, name: str = "") -> ScanResult:
    """Scan every text file under a skill folder. Never raises — an
    unreadable file is skipped, not fatal."""
    skill_path = Path(skill_path)
    name = name or skill_path.name
    if skill_path.is_file():
        files = [skill_path]
    else:
        files = [p for p in sorted(skill_path.rglob("*"))
                 if p.is_file() and p.suffix.lower() in _SCANNABLE]
    findings: list[Finding] = []
    scanned = 0
    for p in files:
        try:
            if p.stat().st_size > 1_000_000:
                continue
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        scanned += 1
        try:
            rel = str(p.relative_to(skill_path))
        except ValueError:
            rel = p.name
        findings.extend(scan_text(text, file=rel))
    return ScanResult(
        skill=name, verdict=_verdict(findings),
        findings=findings, files_scanned=scanned,
    )


def format_report(result: ScanResult, *, limit: int = 12) -> str:
    """A short human-readable scan report."""
    glyph = {"clean": "✓", "caution": "⚠", "danger": "✖"}.get(
        result.verdict, "?")
    head = (f"{glyph} skill '{result.skill}' — {result.verdict} "
            f"({len(result.findings)} finding(s), "
            f"{result.files_scanned} file(s) scanned)")
    if not result.findings:
        return head
    ranked = sorted(result.findings,
                    key=lambda f: _SEVERITY_RANK.get(f.severity, 4))
    lines = [head]
    for f in ranked[:limit]:
        loc = f"{f.file}:{f.line}" if f.file else f"line {f.line}"
        lines.append(f"  [{f.severity}] {f.description} ({loc})")
    if len(ranked) > limit:
        lines.append(f"  … and {len(ranked) - limit} more")
    return "\n".join(lines)
