"""Reply correlation ceiling inside the existing admitted turn/tool path."""
from __future__ import annotations
from contextlib import contextmanager
import json


@contextmanager
def scope(gateway,session_id,request_id):
    from jaeger_agent.tools.messaging import bound_reply_resolver
    def resolve(channel,recipient,message_id):
        from jaeger_ai.core.gateway.server import _control_plane_block
        from jaeger_ai.plugins import get_bridge
        from .bindings import read,SUPPORTED
        if _control_plane_block():raise ValueError('Gateway lifecycle/Stop prevents reply')
        if type(message_id) is not int or message_id<=0 or channel not in SUPPORTED:raise ValueError('Existing channel message required')
        with gateway.store._get_conn() as conn:
            row=conn.execute('SELECT kind,meta_json FROM messages WHERE id=? AND session_id=?',(message_id,session_id)).fetchone()
        if row is None or row['kind']!='channel_message':raise ValueError('Reply target is not incoming data in this conversation')
        meta=json.loads(row['meta_json'] or '{}')
        if meta.get('channel_id')!=channel or meta.get('provider_conversation_id')!=channel+':'+recipient:raise ValueError('Channel recipient does not match saved incoming message')
        session=gateway.store.get_session(session_id) or {};agent=(session.get('metadata') or {}).get('agent_id')
        binding=read(gateway.store,channel);bridge=get_bridge(channel)
        if not agent or binding['agent_id']!=agent or bridge is None or getattr(bridge,'_jaeger_gateway_binding',None)!=binding:raise ValueError('Current inbox/transport binding does not own this reply')
        allowed=getattr(bridge,'_allowed',set())
        if channel=='discord':
            # Discord allowlist names USERS; provider conversation names a CHANNEL.
            author=meta.get('ingress_author_id')
            if not isinstance(author,str) or not author.isdecimal() or not allowed or int(author) not in allowed:
                raise ValueError('Saved ingress author is absent or outside current Discord user allowlist')
        else:
            target=int(recipient) if channel=='telegram' else recipient
            if not allowed or target not in allowed:raise ValueError('Recipient is outside current transport allowlist')
        request=gateway.store.get_request(request_id) if request_id else None
        if not request or request['session_id']!=session_id or request['status'] not in {'admitted','running'}:raise ValueError('An active admitted request is required')
        return {'reply_to_message_id':message_id,'external_message_id':str(meta.get('external_message_id',''))[:200],'session_id':session_id,'request_id':request_id}
    with bound_reply_resolver(resolve):yield
