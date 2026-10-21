"""Channel inbox routing, not execution authority; existing Gateway stores only."""
from __future__ import annotations
import json
from contextlib import closing
SUPPORTED=frozenset({'telegram','discord','imessage'})


def read(store,channel):
    with closing(store._get_conn()) as conn:
        row=conn.execute('SELECT value FROM schema_meta WHERE key=?',('channel_binding:'+channel,)).fetchone()
    value=json.loads(row[0]) if row else {'revision':0,'agent_id':None}
    if not isinstance(value,dict) or type(value.get('revision')) is not int or (value.get('agent_id') is not None and not isinstance(value.get('agent_id'),str)):
        raise ValueError('Invalid saved channel binding; original retained')
    return value


def save(store,channel,agent_id,expected_revision):
    if channel not in SUPPORTED:raise ValueError('Channel has no configured inbox adapter')
    with store._immediate() as conn:
        key='channel_binding:'+channel
        old=conn.execute('SELECT value FROM schema_meta WHERE key=?',(key,)).fetchone()
        value=json.loads(old[0]) if old else {'revision':0,'agent_id':None}
        if type(expected_revision) is not int or value.get('revision')!=expected_revision:raise ValueError('Channel binding changed; reload before saving')
        value={'revision':expected_revision+1,'agent_id':agent_id}
        conn.execute('INSERT INTO schema_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,json.dumps(value)))
    return value


def inbox(gateway,channel,binding):
    """Plugin allowlists/admin gates remain upstream. This callback executes no turn.

    External message identity is mandatory; body is data in the bound bot's
    continuous home feed. A user's subsequent reply is an ordinary new turn.
    """
    agent_id=binding['agent_id']
    def receive(text,*,session_key=None,message_id=None,author_id=None):
        from jaeger_ai.core.gateway.server import _control_plane_block
        if _control_plane_block():raise ValueError('Gateway is stopped or lacks a live lifecycle owner; message not admitted')
        if not session_key or not str(session_key).startswith(channel+':') or not message_id:
            raise ValueError('Provider conversation and message identity required; nothing admitted')
        if not isinstance(text,str) or not text.strip() or len(text)>32000:
            raise ValueError('Message must contain1–32000 characters')
        if read(gateway.store,channel)!=binding:raise ValueError('Channel binding changed; reconnect explicitly')
        if channel=='discord' and (not isinstance(author_id,str) or not author_id.isdecimal() or int(author_id)<=0):
            raise ValueError('Discord ingress author identity required; no channel/user identity inference')
        target=gateway._registry().get_agent(agent_id)
        if target is None:raise ValueError('Bound bot no longer exists; message not admitted')
        home,_=gateway._ensure_agent_home(agent_id,getattr(target,'display_name',None))
        receipt=gateway.store.append_channel_message_once(home,channel=channel,conversation_id=str(session_key),external_id=str(message_id),text=text,author_id=author_id)
        return f"Saved to Jaeger inbox (message {receipt['message_id']}). No bot execution or tool approval was authorized."
    return receive
