"""Exercise storage failure and competing real writers, not model output."""
from concurrent.futures import ThreadPoolExecutor
import json
import subprocess
import sys

import pytest

from jaeger_agent.background.board import Board, BoardStorageError


def test_concurrent_processes_preserve_all_cards_and_comments(tmp_path):
    path = tmp_path / 'board.json'
    card = Board(path).add('shared')
    script = '''
import sys
from pathlib import Path
from jaeger_agent.background.board import Board
board = Board(Path(sys.argv[1]))
for index in range(12):
    label = sys.argv[3] + ':' + str(index)
    board.add(label)
    board.comment(sys.argv[2], label)
'''
    children = [subprocess.Popen([sys.executable, '-c', script, str(path), card.id, str(i)],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                for i in range(4)]
    try:
        for child in children:
            stdout, stderr = child.communicate(timeout=30)
            assert child.returncode == 0, stdout + stderr
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.communicate()
    board = Board(path)
    assert len(board.list()) == 49
    assert len({c['body'] for c in board.get(card.id).comments}) == 48
    assert path.stat().st_mode & 0o077 == 0


def test_concurrent_threads_and_board_instances_preserve_updates(tmp_path):
    path = tmp_path / 'board.json'
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: Board(path).add(str(i)), range(40)))
    assert {c.title for c in Board(path).list()} == {str(i) for i in range(40)}


@pytest.mark.parametrize('raw', ['{broken', '{}', '[]', '{"cards":[null]}',
                               '{"cards":[{"title":"lost identity"}]}'])
def test_unreadable_existing_board_is_never_replaced(tmp_path, raw):
    path = tmp_path / 'board.json'
    path.write_text(raw)
    with pytest.raises(BoardStorageError, match='Existing data was preserved'):
        Board(path).add('must not overwrite existing work')
    assert path.read_text() == raw


def test_failed_atomic_replace_preserves_previous_board(tmp_path, monkeypatch):
    from pathlib import Path
    path = tmp_path / 'board.json'
    Board(path).add('original')
    before = path.read_bytes()

    def fail_replace(*args):
        raise OSError('injected storage failure')

    monkeypatch.setattr(Path, 'replace', fail_replace)
    with pytest.raises(OSError, match='injected'):
        Board(path).add('uncommitted')
    assert path.read_bytes() == before
    assert not list(tmp_path.glob('*.tmp'))
    assert json.loads(before)['cards'][0]['title'] == 'original'
