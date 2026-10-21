"""Two real SQLite connections, bounded deterministic interleavings, owned DB only."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from jaeger_ai.features.knowledge_library import KnowledgeLibrary
from jaeger_ai.features.knowledge_library.managed import DocumentConflict


@pytest.mark.parametrize('action',['save','archive'])
def test_two_connections_reject_stale_writer_after_winner_reservation(tmp_path,action):
    path=tmp_path/'race.db';winner=KnowledgeLibrary(path)
    doc=winner.create_document(title='Owned',content='Original',command_id='race')
    ready,start,attempted=Event(),Event(),Event()
    def stale():
        peer=KnowledgeLibrary(path)
        peer.conn.set_trace_callback(lambda sql:attempted.set() if sql=='BEGIN IMMEDIATE' else None)
        ready.set()
        try:
            assert start.wait(3)
            with pytest.raises(DocumentConflict,match='changed'):
                peer.save_document(doc['id'],title='Stale',content='Overwrite',expected_revision=1)
        finally:peer.close()
    read=winner.managed_document
    def interleave(document_id):
        row=read(document_id)
        if winner.conn.in_transaction and not start.is_set():
            start.set();assert attempted.wait(3)
        return row
    winner.managed_document=interleave
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            loser=executor.submit(stale);assert ready.wait(3)
            if action=='save':result=winner.save_document(doc['id'],title='Winner',content='Winning content',expected_revision=1)
            else:result=winner.archive_document(doc['id'],archived=True,expected_revision=1)
            loser.result(timeout=4)
        assert result['revision']==2
        final=read(doc['id']);assert final['revision']==2 and final['title']!='Stale'
        assert len(winner.document_versions(doc['id']))==2
    finally:start.set();winner.close()


@pytest.mark.parametrize('action',['save','archive'])
def test_write_window_expiry_at_final_commit_rolls_back_all_changes(tmp_path,monkeypatch,action):
    from jaeger_ai.features.knowledge_library import managed
    clock=[0.];monkeypatch.setattr(managed,'_write_time',lambda:clock[0])
    owner=KnowledgeLibrary(tmp_path/'expiry.db');doc=owner.create_document(title='Owned',content='Original',command_id='expire')
    read=owner.managed_document;observations=[]
    def expire_at_commit(document_id):
        row=read(document_id);observations.append(row['revision'])
        if row['revision']==2:clock[0]=6.  # after update, before the owner's final commit guard
        return row
    owner.managed_document=expire_at_commit
    try:
        with pytest.raises(DocumentConflict,match='expired before commit'):
            if action=='save':owner.save_document(doc['id'],title='Expired',content='Must roll back',expected_revision=1)
            else:owner.archive_document(doc['id'],archived=True,expected_revision=1)
        assert observations==[1,2]
        row=read(doc['id']);assert row['revision']==1 and row['content']=='Original' and not row['archived']
        assert len(owner.document_versions(doc['id']))==1
        assert owner.search('Original')[0]['id']==doc['id']
    finally:owner.close()


def test_write_window_expires_while_waiting_for_other_sqlite_writer(tmp_path,monkeypatch):
    from jaeger_ai.features.knowledge_library import managed
    clock=[0.];monkeypatch.setattr(managed,'_write_time',lambda:clock[0])
    path=tmp_path/'wait.db';owner=KnowledgeLibrary(path);doc=owner.create_document(title='Owned',content='Original',command_id='wait')
    ready,start,attempted=Event(),Event(),Event()
    def late_writer():
        peer=KnowledgeLibrary(path);peer.conn.set_trace_callback(lambda sql:attempted.set() if sql=='BEGIN IMMEDIATE' else None);ready.set()
        try:
            assert start.wait(3)
            with pytest.raises(DocumentConflict,match='expired'):
                peer.save_document(doc['id'],title='Expired',content='No write',expected_revision=1)
        finally:peer.close()
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            work=executor.submit(late_writer);assert ready.wait(3)
            owner.conn.execute('BEGIN IMMEDIATE');start.set();assert attempted.wait(3)
            clock[0]=6.;owner.conn.commit();work.result(timeout=4)
        assert owner.managed_document(doc['id'])['revision']==1
        assert len(owner.document_versions(doc['id']))==1
    finally:start.set();owner.conn.rollback();owner.close()


@pytest.mark.parametrize('action',['save','archive'])
def test_committed_snapshot_is_not_replaced_by_a_later_writers_result(tmp_path,action):
    path=tmp_path/'receipt.db';owner=KnowledgeLibrary(path);peer=KnowledgeLibrary(path)
    doc=owner.create_document(title='Owned',content='Original',command_id='receipt')
    # Real SQLite commit, then another connection wins before caller returns.
    class InterleaveCommit:
        def __init__(self,conn):self.conn=conn;self.once=True
        def __getattr__(self,key):return getattr(self.conn,key)
        def __enter__(self):self.conn.__enter__();return self
        def __exit__(self,*args):
            result=self.conn.__exit__(*args)
            if self.once and args[0] is None:
                self.once=False
                peer.save_document(doc['id'],title='Later writer',content='Later value',expected_revision=2) if action=='save' else peer.archive_document(doc['id'],archived=False,expected_revision=2)
            return result
    owner.conn=InterleaveCommit(owner.conn)
    try:
        result=owner.save_document(doc['id'],title='First winner',content='First value',expected_revision=1) if action=='save' else owner.archive_document(doc['id'],archived=True,expected_revision=1)
        assert result['revision']==2
        assert peer.managed_document(doc['id'])['revision']==3
        if action=='save':assert result['content']=='First value'
        else:assert result['archived'] is True
    finally:owner.close();peer.close()
