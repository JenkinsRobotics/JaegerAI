"""Real owned Gateway HTTP journey for documents and corrected specialist memory.

Synthetic content only. Proves durable storage/search and owner authority, not
that a live model retrieves or reasons correctly about a document.
"""
from __future__ import annotations

import pytest
from urllib.error import HTTPError
from dev.tests.fixtures.owned_gateway import OwnedGateway

pytestmark = [pytest.mark.integration, pytest.mark.subprocess]


def test_document_and_corrected_memory_reopen_after_gateway_restart(tmp_path):
    gateway = OwnedGateway(tmp_path)
    try:
        gateway.start()
        _, created = gateway.request('/v1/library/documents', {
            'operation_id': 'journey-document', 'title': 'Acceptance reference',
            'content': 'Reference beacon ORBIT-7. Verified local artifact only.',
        }, caller='webui')
        document = created['document']
        document_path = '/v1/library/documents/' + document['id']
        _, found = gateway.request('/v1/library/search?q=ORBIT', caller='webui')
        assert any(row['id'] == document['id'] for row in found['results'])
        assert 'ORBIT-7' in gateway.request(document_path, caller='webui')[1]['content']
        # Read-only peer credentials cannot use the owner's Library surface.
        with pytest.raises(HTTPError) as denied:
            gateway.request(document_path, caller='a2a')
        assert denied.value.code == 403

        _, agent = gateway.request('/v1/agents', {
            'name': 'acceptance-memory', 'role': 'specialist', 'operation_id': 'journey-agent',
        }, caller='webui')
        memory_path = '/v1/agents/' + agent['id'] + '/memory'
        _, empty = gateway.request(memory_path, caller='webui')
        _, saved = gateway.request(memory_path, {
            'operation_id': 'journey-memory', 'expected_revision': empty['revision'],
            'action': 'replace', 'text': 'Synthetic preference: short explanations.',
        }, caller='webui')
        correction = {
            'operation_id': 'journey-correction', 'expected_revision': saved['revision'],
            'action': 'replace', 'text': 'Synthetic preference: detailed explanations.',
        }
        _, corrected = gateway.request(memory_path, correction, caller='webui')
        assert gateway.request(memory_path, correction, caller='webui')[1] == corrected
        with pytest.raises(HTTPError) as stale:
            gateway.request(memory_path, {**correction, 'operation_id': 'journey-stale', 'text': 'Lost edit'}, caller='webui')
        assert stale.value.code == 409

        gateway.stop()
        gateway.start()
        reopened = gateway.request(document_path, caller='webui')[1]
        assert reopened['digest'] == document['digest']
        assert reopened['content'] == 'Reference beacon ORBIT-7. Verified local artifact only.'
        memory = gateway.request(memory_path + '?q=detailed', caller='webui')[1]
        assert memory['revision'] == corrected['revision']
        assert memory['notes'] == 'Synthetic preference: detailed explanations.\n'
        assert memory['search']['matches']
        assert 'short explanations' not in memory['notes']
        # Reusing the durable command does not create another correction/version.
        assert gateway.request(memory_path, correction, caller='webui')[1] == corrected
        assert gateway.request(memory_path, caller='webui')[1]['versions'] == memory['versions']
    finally:
        gateway.stop()
