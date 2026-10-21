import pytest
from jaeger_ai.features.knowledge_library import KnowledgeLibrary
from jaeger_ai.features.knowledge_library.managed import DocumentConflict


def test_versions_conflicts_recoverable_archive_and_same_command(tmp_path):
    library = KnowledgeLibrary(tmp_path/'library.db')
    original = library.create_document(title='Owned', content='First revision', command_id='owned-create')
    assert library.create_document(title='Owned', content='First revision', command_id='owned-create')['id'] == original['id']
    with pytest.raises(DocumentConflict):
        library.create_document(title='Changed', content='Other', command_id='owned-create')
    updated = library.save_document(original['id'], title='Owned', content='Second revision', expected_revision=1)
    assert updated['revision'] == 2
    with pytest.raises(DocumentConflict):
        library.save_document(original['id'], title='Stale', content='Overwrite', expected_revision=1)
    archived = library.archive_document(original['id'], archived=True, expected_revision=2)
    assert library.search('Second revision') == []
    assert library.managed_documents() == []
    assert len(library.managed_documents(include_archived=True)) == 1
    with pytest.raises(DocumentConflict):
        library.restore_document_version(original['id'], revision=1, expected_revision=archived['revision'])
    restored = library.archive_document(original['id'], archived=False, expected_revision=archived['revision'])
    reverted = library.restore_document_version(original['id'], revision=1, expected_revision=restored['revision'])
    assert reverted['content'] == 'First revision' and reverted['revision'] == 5
    assert len(library.document_versions(original['id'])) == 5
    assert library.create_document(title='Owned', content='First revision', command_id='owned-create')['revision'] == 5
    library.close()
    reopened = KnowledgeLibrary(tmp_path/'library.db')
    assert reopened.managed_document(original['id'])['revision'] == 5
    assert reopened.search('First revision')[0]['id'] == original['id']
    reopened.close()


def test_export_uses_reviewed_saved_revision_without_access_grants_or_mutation(tmp_path):
    from jaeger_ai.features.knowledge_library import KnowledgeLibrary
    lib=KnowledgeLibrary(tmp_path/'owned-export.db')
    try:
        doc=lib.create_document(title='Owned export',content='Literal saved content',command_id='owned-export')
        snapshot=lib.export_document(doc['id'],expected_revision=1,expected_digest=doc['digest'])
        assert snapshot['format']=='jaeger.document.snapshot' and snapshot['access']=='manual_local_export_no_recipient_grant'
        assert snapshot['document']['content']=='Literal saved content' and snapshot['document']['revision']==1
        assert set(snapshot['document'])=={'id','title','content','revision','digest','archived'}
        lib.save_document(doc['id'],title='Owned export',content='Newer content',expected_revision=1)
        from jaeger_ai.features.knowledge_library.managed import DocumentConflict
        with pytest.raises(DocumentConflict):lib.export_document(doc['id'],expected_revision=1,expected_digest=doc['digest'])
        assert lib.managed_document(doc['id'])['content']=='Newer content'
        assert len(lib.document_versions(doc['id']))==2
    finally:lib.close()
