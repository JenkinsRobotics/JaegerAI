"""One Roundtable control registry and deterministic agreement rules.

Native agents supply proposals and ballots. Only the orchestrator classifies
agreement; prose, missing votes, and model-generated evidence labels cannot.
"""
import hashlib
import json
import re
from .roundtable_progress import budgets

MEMBERS = ('jaeger', 'hermes', 'openclaw')
MODES = {
    'ask': 'Independent answers, one discussion, then a recorded decision.',
    'collaborate': 'Volunteer for bounded tasks, assign owners, combine results.',
    'quick': 'One eligible member answers.',
    'vote': 'Independent proposals followed by recorded ballots.',
    'review': 'One proposer, followed by peer critique and a decision.',
    'incident': 'Separate diagnostic, evidence, and remediation-proposal owners.',
}
COLLABORATION_TASKS = {
    'analysis': 'Analyze the request and gather relevant evidence within existing permissions.',
    'implementation': 'Carry out only the implementation the user authorized; otherwise provide a concrete proposal.',
    'review': 'Independently review findings and proposed changes; identify gaps and verification needs.',
}


def assign_owners(offers, eligible):
    """Unique bounded assignments; explicit volunteers precede fallback owners."""
    available = list(eligible)
    preferences = {}
    for member in available:
        value = structured(offers.get(member, '')).get('volunteer_for', [])
        preferences[member] = value if isinstance(value, list) and all(
            isinstance(task, str) and task in COLLABORATION_TASKS for task in value) else []
    assignments = []
    for task, description in COLLABORATION_TASKS.items():
        volunteers = [m for m in available if task in preferences[m]]
        owner = volunteers[0] if volunteers else None
        assignments.append({'task': task, 'description': description, 'owner': owner,
                            'assignment_source': 'volunteered' if volunteers else 'unassigned'})
        if owner:
            available.remove(owner)
    # Reserve explicit volunteers for all tasks before filling unclaimed work.
    for assignment in assignments:
        if assignment['owner'] is None and available:
            assignment.update(owner=available.pop(0), assignment_source='orchestrator')
    return assignments


def registry():
    return {'modes': [{'id': mode, 'command': '/' + mode, 'description': description}
                      for mode, description in MODES.items()],
            'members': [{'id': member, 'mention': '@' + member} for member in MEMBERS],
            'mentions': ['@all', *['@' + member for member in MEMBERS]],
            'chair_policies': ['rotate', 'least_involved', *MEMBERS],
            'default_mode': 'ask'}


def _members(value, label, *, empty=False):
    if not isinstance(value, (list, tuple)) or any(v not in MEMBERS for v in value):
        raise ValueError(f'{label} must contain known Roundtable members')
    if len(value) != len(set(value)) or (not value and not empty):
        raise ValueError(f'{label} must be unique and nonempty')
    return list(value)


def plan(message, options=None, preferences=None):
    if not isinstance(message, str) or not message.strip() or len(message) > 64000:
        raise ValueError('Roundtable requires a message of 1..64000 characters')
    if options is not None and not isinstance(options, dict):
        raise ValueError('Roundtable options must be an object')
    options = options or {}
    if set(options) - {'mode', 'members', 'muted', 'chair', 'budgets'}:
        raise ValueError('Unknown Roundtable option')
    prefs = {**(preferences or {}), **options}
    configured = _members(prefs.get('members', MEMBERS), 'members')
    muted = _members(prefs.get('muted', []), 'muted', empty=True)
    if set(muted) - set(configured):
        raise ValueError('Only table members can be muted')
    eligible = [m for m in configured if m not in muted]
    if not eligible:
        raise ValueError('At least one table member must be unmuted')
    mode = prefs.get('mode', 'ask')
    if not isinstance(mode, str) or mode not in MODES:
        raise ValueError('Unknown Roundtable mode')
    text = message.strip()
    command = re.match(r'^/(\w+)\b\s*', text)
    if command:
        mode = command.group(1).lower()
        if mode not in MODES:
            raise ValueError('Unknown Roundtable command; consult the capability registry')
        text = text[command.end():].strip()
    elif 'mode' not in options and prefs.get('mode', 'ask') == 'ask':
        for candidate, words in (
            ('incident', r'\b(?:incident|outage|production failure)\b'),
            ('review', r'\b(?:review|critique|audit)\b'),
            ('vote', r'\b(?:vote|ballot|choose between)\b'),
            ('collaborate', r'\b(?:collaborate|work together|divide|who wants)\b'),
        ):
            if re.search(words, text, re.I):
                mode = candidate
                break
    mentions = re.findall(r'(?<![\w@])@(jaeger|hermes|openclaw|all)\b', text, re.I)
    selected = set(m.lower() for m in mentions)
    if selected - {'all'} - set(eligible):
        raise ValueError('A mentioned member is muted or not part of this table')
    participants = [m for m in eligible if 'all' in selected or not selected or m in selected]
    if mode == 'quick' and len(participants) > 1:
        preferred = 'openclaw' if re.search(r'\bopenclaw\b', text, re.I) else (
            'hermes' if re.search(r'\b(?:hermes|container)\b', text, re.I) else 'jaeger')
        participants = [preferred if preferred in participants else participants[0]]
    chair = prefs.get('chair', 'rotate')
    if not isinstance(chair, str) or chair not in {'rotate', 'least_involved', *configured}:
        raise ValueError('Chair must be a table member or a supported selection policy')
    if chair in muted:
        raise ValueError('The selected chair is muted')
    if not text:
        raise ValueError('A Roundtable command needs a question or task')
    return {'mode': mode, 'message': text, 'participants': participants,
            'chair': chair, 'budgets': budgets(options.get('budgets')),
            'preferences': {'mode': prefs.get('mode', 'ask'),
                'members': configured, 'muted': muted, 'chair': chair}}


def chair_for(plan, session, turn_id, successful, involvement, *, previous=None):
    eligible = [m for m in plan['participants'] if m in successful]
    if not eligible:
        return None
    policy = plan['chair']
    if policy in MEMBERS:
        # Do not silently replace a user-selected unavailable chair.
        return policy if policy in eligible else None
    if policy == 'least_involved':
        count = min(involvement.get(m, 0) for m in eligible)
        eligible = [m for m in eligible if involvement.get(m, 0) == count]
    # A fresh hash per turn can repeatedly choose the same chair. Start from a
    # stable table position, then advance past the persisted previous chair.
    if previous in MEMBERS:
        start = (MEMBERS.index(previous) + 1) % len(MEMBERS)
    else:
        start = int.from_bytes(hashlib.sha256(session.encode()).digest()[:4], 'big') % len(MEMBERS)
    return next(MEMBERS[(start + step) % len(MEMBERS)] for step in range(len(MEMBERS))
                if MEMBERS[(start + step) % len(MEMBERS)] in eligible)


def structured(text):
    """Only an explicit single metadata block is accepted; never parse prose votes."""
    blocks = re.findall(r'```roundtable\s*\n(.*?)\n```', text or '', re.S)
    if len(blocks) != 1:
        return {}
    try:
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('Duplicate ballot/metadata key')
                result[key] = value
            return result
        value = json.loads(blocks[0], object_pairs_hook=unique)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def decide(participants, proposals, discussion, failed=()):
    """Each eligible member has exactly one explicit vote per proposal.

    Abstentions, invalid/missing votes and failed members all remain in the
    denominator. A majority is strictly more than half of the selected table.
    """
    votes = {}
    for member in participants:
        block = structured(discussion.get(member, '')) if member not in failed else {}
        ballot = block.get('ballot', {})
        votes[member] = ballot if isinstance(ballot, dict) else {}
    results = []
    for proposal in proposals:
        groups = {key: [] for key in ('support', 'oppose', 'abstain', 'missing', 'failed')}
        for member in participants:
            vote = votes[member].get(proposal['id'])
            category = 'failed' if member in failed else vote if vote in ('support', 'oppose', 'abstain') else 'missing'
            groups[category].append(member)
        support = len(groups['support'])
        outcome = 'unanimous' if support == len(participants) else (
            'majority' if support > len(participants) / 2 else 'no_agreement')
        if proposal.get('truncated'):
            outcome = 'insufficient_context'
        results.append({**proposal, 'outcome': outcome, 'votes': groups,
                        'evidence_status': 'reported', 'verified_by_model_label': False})
    return {'participants': list(participants), 'proposals': results,
            'rule': 'explicit_ballots_of_all_selected_members',
            'agreed_proposal_ids': [r['id'] for r in results if r['outcome'] == 'unanimous'],
            'open_questions': [{'proposal_id': r['id'], 'reason': r['outcome']}
                               for r in results if r['outcome'] != 'unanimous'],
            'consensus': bool(results) and all(r['outcome'] == 'unanimous' for r in results)}


def peer_context(answers, limit=12000):
    if not answers:
        return 'No successful peer responses.'
    allowance = max(1, limit // len(answers) - 100)
    return '\n\n'.join(f'{member}:\n{text[:allowance]}' +
        ('\n[Truncated; omitted text is not evidence of agreement.]' if len(text) > allowance else '')
        for member, text in answers.items())
