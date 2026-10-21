"""Original local webhook transport/admission bounds; never permission grants."""
SUBSCRIPTION_ID_PATTERN = r'[A-Za-z0-9_.:-]{1,100}'
FILTER_TOKEN_PATTERN = r'[A-Za-z0-9_.:@/-]{1,100}'
MAX_EVENT_BODY_BYTES = 64_000
MAX_PROPOSAL_BYTES = 16_000
HISTORY_LIMIT = 100
