# Security policy

Report suspected vulnerabilities privately through GitHub's security-advisory
workflow for this repository. Do not include credentials, user data, or an
active exploit in a public issue.

## Supported code

Security fixes target the current default branch and the latest published
release. Older revisions should be upgraded before a report is reproduced.

## Audited dependency exception

As of 2026-08-27, `llama-cpp-python` requires `diskcache`, whose latest
release (5.6.3) is covered by CVE-2025-69872 / PYSEC-2026-2447. The advisory
requires an attacker to write a malicious pickle into a DiskCache directory
that the victim later reads, and no patched DiskCache release exists.

Jaeger does not instantiate `llama_cpp.LlamaDiskCache` or otherwise use
DiskCache's pickle-backed cache. The package is present only as a transitive
requirement of the default local-model backend, so the vulnerable
deserialization path is not reachable in the shipped configuration. CI keeps
the advisory as one explicit exception while failing on every other known
dependency vulnerability. Remove the exception when either dependency ships
a patched release, or before enabling a disk-backed llama.cpp prompt cache.

References:

- https://github.com/advisories/GHSA-w8v5-vhqr-4h9v
- https://pypi.org/project/diskcache/
