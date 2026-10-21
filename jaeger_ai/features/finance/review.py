"""Local financial review metadata, not a payment processor or spending grant."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from contextlib import closing
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from .models import ApprovalTier
from .security import SecuritySanitizer

# One policy producer shared by ApprovalEngine, status and local review controls.
OPERATION_TIERS = {
    **dict.fromkeys(('read_accounts', 'read_transactions', 'calculate_budget', 'finance_summary', 'finance_audit', 'finance_transactions', 'finance_inbox', 'generate_briefing'), ApprovalTier.AUTONOMOUS),
    **dict.fromkeys(('categorize_merchant', 'modify_budget', 'create_rule', 'bulk_review'), ApprovalTier.ONE_CLICK),
    **dict.fromkeys(('disconnect_account', 'purge_all', 'delete_rule', 'export_data'), ApprovalTier.EXPLICIT_CONFIRM),
}
ID = re.compile(r'[A-Za-z0-9_-]{1,100}')
STATUSES = {'pending', 'approved', 'rejected', 'expired', 'execution_unknown', 'completed', 'failed', 'cancelled'}

def _status(row):
    return row['status'] if row['status'] in STATUSES else 'unsupported_status'



def policy():
    return {'money_movement': 'blocked', 'payment_cards': 'unsupported', 'provider': 'not_probed',
            'spending_limits': 'no_payment_authority', 'approval_scope': 'local_review_record_only',
            'unknown_operations': 'blocked', 'execution_supported': False,
            'operations': [{'id': name, 'tier': tier.value} for name, tier in OPERATION_TIERS.items()]}


def revision(row):
    return hashlib.sha256(json.dumps(dict(row), sort_keys=True).encode()).hexdigest()


def _expired(row):
    if not row['expires_at']:
        return False
    try:
        at = datetime.fromisoformat(row['expires_at'])
        return at.tzinfo is None or at <= datetime.now(UTC)
    except (ValueError, TypeError):
        return True


def _proposed_change(payload, kind):
    fields = {'categorize_merchant': ('merchant', 'category'), 'create_rule': ('name', 'pattern', 'target_category'),
              'modify_budget': ('category', 'month', 'budgeted')}.get(kind)
    if not fields or not isinstance(payload, dict):
        return None
    result = {}
    for key in fields:
        value = payload.get(key)
        if key == 'budgeted':
            try:
                number = Decimal(str(value))
                if not number.is_finite() or not 0 <= number <= Decimal(1000000000):
                    return None
                result[key] = str(number)
            except (InvalidOperation, ValueError):
                return None
        else:
            if not isinstance(value, str) or not value.strip() or len(value) > 200:
                return None
            safe = SecuritySanitizer.redact_pii(SecuritySanitizer.sanitize_untrusted_text(value))
            if safe != value:
                return None  # Never approve a scope hidden by redaction/truncation.
            if key == 'month' and re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', value) is None:
                return None
            result[key] = safe
    return result


def project(row):
    tier = OPERATION_TIERS.get(row['action_type'], ApprovalTier.BLOCKED)
    safe = {'id': row['id'], 'revision': revision(row), 'operation': row['action_type'] if row['action_type'] in OPERATION_TIERS else 'unsupported_operation',
            'policy_tier': tier.value, 'stored_status': _status(row), 'status': 'expired' if row['status'] == 'pending' and _expired(row) else _status(row),
            'expires_at': datetime.fromisoformat(row['expires_at']).isoformat() if row['expires_at'] and not _expired(row) else None, 'settlement_status': 'not_observed', 'execution_supported': False}
    try:
        payload = json.loads(row['payload_json'])
    except (ValueError, TypeError):
        payload = {}
    change = _proposed_change(payload, row['action_type'])
    if change:
        safe['proposed_change'] = change
    safe['can_record_review'] = bool(change) and safe['status'] == 'pending' and tier == ApprovalTier.ONE_CLICK and row['tier'] == ApprovalTier.ONE_CLICK.value
    safe['can_deny'] = safe['status'] == 'pending'
    # No raw payload, rationale, account/card data or provider credentials.
    # Optional declared spending scope is displayed, never converted to a grant.
    try:
        amount = Decimal(str(payload.get('amount')))
        currency, merchant = payload.get('currency'), payload.get('merchant')
        if amount.is_finite() and 0 < amount <= Decimal(1000000000) and isinstance(currency, str) and re.fullmatch(r'[A-Z]{3}', currency) and isinstance(merchant, str):
            safe['declared_scope'] = {'amount': str(amount), 'currency': currency,
                                      'merchant': SecuritySanitizer.redact_pii(SecuritySanitizer.sanitize_untrusted_text(merchant))[:120]}
    except (InvalidOperation, ValueError, TypeError, AttributeError):
        pass
    return safe


def snapshot(store):
    with closing(store._get_conn()) as conn:
        rows = conn.execute('SELECT * FROM pending_actions ORDER BY created_at DESC,id LIMIT 50').fetchall()
        return {'state': 'existing_local_store', 'policy': policy(), 'actions': [project(row) for row in rows], 'limit': 50}


def operation(store, operation_id):
    if not isinstance(operation_id, str) or ID.fullmatch(operation_id) is None:
        raise ValueError('Valid finance review operation identity required')
    with closing(store._get_conn()) as conn:
        rows = conn.execute("SELECT details_json FROM audit_log WHERE action='review_decision' AND json_extract(details_json,'$.operation_id')=? ORDER BY id DESC LIMIT 2", (operation_id,)).fetchall()
    if len(rows) != 1:
        return None
    return json.loads(rows[0][0])['receipt']


def decide(store, action_id, decision, *, expected_revision=None, operation_id=None, actor='operator'):
    if not isinstance(action_id, str) or ID.fullmatch(action_id) is None or not isinstance(decision, str) or decision not in {'record_review', 'deny'}:
        raise ValueError('Supported local review decision required')
    oid = operation_id or str(uuid.uuid4())
    if not isinstance(oid, str) or ID.fullmatch(oid) is None:
        raise ValueError('Stable finance review operation identity required')
    fp = hashlib.sha256(json.dumps([actor, action_id, decision, expected_revision]).encode()).hexdigest()
    with closing(store._get_conn()) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        old = conn.execute("SELECT details_json FROM audit_log WHERE action='review_decision' AND json_extract(details_json,'$.operation_id')=? LIMIT 2", (oid,)).fetchall()
        if old:
            if len(old) != 1 or json.loads(old[0][0])['fingerprint'] != fp:
                raise ValueError('Finance review operation identity conflicts; inspect without retry')
            return json.loads(old[0][0])['receipt']
        row = conn.execute('SELECT * FROM pending_actions WHERE id=?', (action_id,)).fetchone()
        conn.execute('SAVEPOINT review_mutation')
        receipt = {'ok': False, 'operation_id': oid, 'action_id': action_id, 'decision': decision,
                   'review_only': True, 'execution_performed': False, 'reviewed_revision': expected_revision, 'http_status': 409}
        if row is not None and project(row).get('declared_scope'):
            receipt['declared_scope'] = project(row)['declared_scope']
        if row is None:
            receipt.update(error='Local review request not found', status='missing', http_status=404)
        elif expected_revision is not None and expected_revision != revision(row):
            receipt.update(error='Request changed; read and review the current scope', status='conflict')
        elif row['status'] != 'pending':
            receipt.update(error='Request is already settled or unknown; no replay', status=_status(row))
        elif _expired(row):
            conn.execute("UPDATE pending_actions SET status='expired' WHERE id=? AND status='pending'", (action_id,))
            receipt.update(error='Local review expired; no action executed', status='expired')
        elif decision == 'record_review' and not project(row)['can_record_review']:
            receipt.update(error='This operation is blocked or not supported for local review; no spending authority', status='blocked', http_status=403)
        else:
            status = 'approved' if decision == 'record_review' else 'rejected'
            conn.execute("UPDATE pending_actions SET status=? WHERE id=? AND status='pending'", (status, action_id))
            receipt.update(ok=True, status=status, http_status=200)
        store.append_audit('review_decision', actor, {'operation_id': oid, 'fingerprint': fp, 'receipt': receipt}, connection=conn)
        if receipt['ok'] and decision == 'record_review' and _expired(row):
            conn.execute('ROLLBACK TO review_mutation')
            conn.execute("UPDATE pending_actions SET status='expired' WHERE id=? AND status='pending'", (action_id,))
            receipt.update(ok=False, status='expired', http_status=409, error='Review expired before commit; no action executed')
            store.append_audit('review_decision', actor, {'operation_id': oid, 'fingerprint': fp, 'receipt': receipt}, connection=conn)
        conn.execute('RELEASE review_mutation')
    return receipt
