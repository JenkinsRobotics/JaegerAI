"""Transport submission truth for the existing approval/tool/effect-ledger path."""
from __future__ import annotations
from jaeger_ai.core.redaction import redact_text
from jaeger_agent.cognition.effects import EffectOutcomeUnknown


class ChannelDeliveryUnknown(EffectOutcomeUnknown):
    execution_unknown=True


def checked_receipt(result):
    """Only explicit transport acceptance is success; unknown must leave ledger pending.

    A server acknowledgment is not evidence that a recipient read the message.
    Known not-started failures can settle, but ambiguous/partial sends cannot.
    """
    if not isinstance(result,dict):
        raise ChannelDeliveryUnknown('Transport returned no authoritative receipt; do not retry')
    if result.get('execution_unknown') or (result.get('sent') is not True and result.get('effect')!='not_started'):
        partial={'sent':False,'effect':'outcome_unknown','delivery_verified':False,'execution_unknown':True}
        if isinstance(result.get('message_ids'),list):partial['message_ids']=[redact_text(str(v))[:200] for v in result['message_ids'][:100] if isinstance(v,(str,int)) and not isinstance(v,bool)]
        raise ChannelDeliveryUnknown('Transport submission outcome unknown or partial; reconcile without retry',partial)
    if result.get('sent') is not True:
        return {'sent':False,'effect':'not_started','execution_unknown':False,'delivery_verified':False,
                'error':'Transport rejected before submission; inspect current connection/recipient'}
    receipt={'sent':True,'effect':'transport_accepted','execution_unknown':False,'delivery_verified':False}
    for key in ('message_id','chat_id','channel_id','recipient'):
        if isinstance(result.get(key),(str,int)) and not isinstance(result.get(key),bool):receipt[key]=redact_text(str(result[key]))[:200]
    if isinstance(result.get('message_ids'),list):
        receipt['message_ids']=[redact_text(str(v))[:200] for v in result['message_ids'][:100] if isinstance(v,(str,int)) and not isinstance(v,bool)]
    return receipt
