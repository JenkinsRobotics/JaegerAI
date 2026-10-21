"""Bounded, opt-in transport counters owned by the existing Gateway process.

Volatile observation, not an execution journal or telemetry service. Never accepts
raw frames/errors/prompts/headers; a restart loses counters and never restarts capture.
"""
from __future__ import annotations
from collections import OrderedDict
from copy import deepcopy
import hashlib
import threading
import time
import uuid

CODES={'malformed_json':'parser','frame_oversize':'parser','transport_idle':'transport','subscriber_error':'subscriber'}
MAX_EVENTS=128
MAX_SECONDS=300


class TransportDiagnostics:
    def __init__(self, *, clock=time.monotonic, wall=time.time):
        self.boot_id=uuid.uuid4().hex
        self._clock,self._wall=clock,wall
        self._lock=threading.RLock()
        self._capture=None
        self._deadline=0.
        self._events=OrderedDict()

    def _expire(self):
        if self._capture and self._capture['state']=='active' and self._clock()>=self._deadline:
            self._capture['state']='expired'

    @staticmethod
    def _uuid(value):
        try:
            if not isinstance(value,str) or len(value)>36:raise ValueError()
            return uuid.UUID(value).hex
        except (ValueError,AttributeError):raise ValueError('Valid diagnostic identity required') from None

    def snapshot(self):
        with self._lock:
            self._expire()
            return {'boot_id':self.boot_id,'scope':'current_gateway_volatile_counters','capture':deepcopy(self._capture),
                'events':list(deepcopy(self._events).values()),'max_events':MAX_EVENTS,'max_seconds':MAX_SECONDS,'codes':dict(CODES),
                'retention':'Most recent capture in memory only; no raw data. Gateway restart loses counters without restarting capture.'}

    def start(self, operation_id, duration):
        oid=self._uuid(operation_id)
        if type(duration) is not int or not 1<=duration<=MAX_SECONDS:raise ValueError('Diagnostic duration must be 1–300 seconds')
        with self._lock:
            self._expire()
            if self._capture and self._capture['operation_id']==oid:
                if self._capture['duration_seconds']!=duration:raise ValueError('Diagnostic operation identity conflict')
                return self.snapshot() # No expiry extension or automatic restart.
            if self._capture and self._capture['state']=='active':raise ValueError('Stop the current capture before starting another')
            now=self._wall();self._deadline=self._clock()+duration;self._events.clear()
            self._capture={'id':uuid.uuid4().hex,'operation_id':oid,'state':'active','started_at':now,'expires_at':now+duration,
                'duration_seconds':duration,'occurrences':0,'unique_receipts':0,'overflow_occurrences':0,'saturated':False}
            return self.snapshot()

    def stop(self, capture_id):
        cid=self._uuid(capture_id)
        with self._lock:
            self._expire()
            if not self._capture or self._capture['id']!=cid:raise ValueError('Capture not present in this Gateway process')
            if self._capture['state']=='active':self._capture['state']='stopped'
            return self.snapshot()

    def report(self, capture_id, event_id, code, *, session_id=None, request_id=None):
        cid,eid=self._uuid(capture_id),self._uuid(event_id)
        if not isinstance(code,str) or code not in CODES:raise ValueError('Unsupported diagnostic category')
        # Only opaque references survive; endpoint/request ownership is checked by Gateway.
        ref=lambda value:hashlib.sha256(value.encode()).hexdigest() if value else None
        event={'receipt_ref':ref(eid),'code':code,'stage':CODES[code],'session_ref':ref(session_id),'request_ref':ref(request_id)}
        with self._lock:
            self._expire()
            if not self._capture or self._capture['id']!=cid or self._capture['state']!='active':raise ValueError('Diagnostic capture inactive or expired; no report retained')
            current=self._events.get(event['receipt_ref'])
            if current and any(current[key]!=value for key,value in event.items()):raise ValueError('Diagnostic receipt belongs to another cause')
            cap=self._capture
            if cap['occurrences']>=1_000_000:
                cap['saturated']=True;return {'accepted':False,'reason':'counter_limit'}
            cap['occurrences']+=1
            if current:current['occurrences']+=1
            elif len(self._events)<MAX_EVENTS:
                self._events[event['receipt_ref']]={**event,'occurrences':1}
                cap['unique_receipts']+=1
            else:cap['overflow_occurrences']+=1
            return {'accepted':True,'scope':'metadata_counters_only'}
