# Personal Finance Assistant (Monarch Money Copilot)

A private, Mac-native, explainable personal financial copilot for JaegerAI.
Monarch Money serves as the external source of truth without competing financial ledgers.

Phase 1 Status: **Safe Read-Only MVP**. No external mutations can reach Monarch.

## Architecture

```text
jaeger_ai/features/finance/
├── models.py              # Normalized domain dataclasses (Account, Transaction, Budget, Rule)
├── security.py            # Keychain master key management, AES-256-GCM cipher, PII redactor
├── store.py               # FinanceStore (encrypted SQLite schema, transactions, audit trail)
├── provider.py            # FinanceProvider protocol interface
├── providers/
│   ├── monarch.py         # MonarchProvider (read-only adapter wrapping monarchmoney)
│   └── importer.py        # ImportProvider (Monarch CSV export & synthetic fixture generator)
├── sync.py                # SyncEngine (idempotent synchronization, duplicate suppression)
├── classifier.py          # TransactionClassifier (7-tier hierarchy, transfer detection, inbox)
├── budget.py              # BudgetEngine (actual vs budgeted, pacing velocity, daily allowances)
├── cashflow.py            # CashFlowEngine (liquidity runway, upcoming bills projection)
├── anomaly.py             # AnomalyDetector (duplicates, fee spikes, price increases)
├── memory.py              # FinanceMemory (explicit operator-approved preferences and rules)
├── approval.py            # ApprovalEngine (approval policy enforcement, blocks money movement)
├── audit.py               # AuditLog (immutable cryptographically chained SHA-256 audit log)
├── briefing.py            # BriefingEngine (daily, weekly, monthly executive briefings)
├── cli.py                 # Terminal interface (`jaeger finance`)
└── tools.py               # Agent-facing tools (`finance_summary`, `finance_audit`, etc.)
```

## Security & Privacy Doctrine

1. **Local-First & Encrypted At Rest**:
   Master key stored in macOS Keychain (`/usr/bin/security`) with secure 0600 file fallback. Sensitive statement names, account numbers, and notes are AES-256-GCM encrypted in SQLite.
2. **Zero In-Repo State**:
   All database files and session tokens reside strictly under `~/.jaeger/finance/` (or `$JAEGER_STATE_DIR/finance/`), never in git.
3. **Strictly Read-Only (Phase 1)**:
   The assistant cannot modify categories, balances, tags, or transactions in Monarch without explicit operator confirmation. Money movement is permanently blocked by policy.
4. **Untrusted Data Sanitization**:
   All merchant statement strings and transaction notes are sanitized against prompt-injection markers before classification or evaluation.

## CLI Usage

```bash
# View financial summary & cash runway
jaeger finance summary

# Generate executive briefings
jaeger finance briefing --daily
jaeger finance briefing --weekly
jaeger finance briefing --monthly

# Review transaction inbox (unreviewed charges, low confidence, duplicates)
jaeger finance inbox

# Idempotently synchronize from connected provider
jaeger finance sync --days 30

# Import from Monarch CSV export (offline fallback)
jaeger finance import /path/to/monarch_export.csv

# Seed realistic demonstration data (zero credentials required)
jaeger finance seed-demo

# Purge all local financial records (privacy control)
jaeger finance purge --force
```
