"""Tests for the unauthenticated GET /api/ui/users endpoint."""
import os
import socket
import subprocess
import sys
import time

import httpx
import pytest

OWNER_TOKEN = 'test-owner-token-xyz'


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


@pytest.fixture(scope='module')
def server():
    port = _find_free_port()
    db_path = f'/tmp/zikra_test_users_{port}.db'
    base = f'http://127.0.0.1:{port}'
    env = {
        **os.environ,
        'ZIKRA_TOKEN': OWNER_TOKEN,
        'ZIKRA_DB_PATH': db_path,
        'ZIKRA_SKIP_ONBOARDING': '1',
        'DB_BACKEND': 'sqlite',
    }
    proc = subprocess.Popen(
        [sys.executable, '-m', 'zikra', '--port', str(port)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    deadline = time.time() + 10
    while time.time() < deadline:
        if proc.poll() is not None:
            output = proc.stdout.read() if proc.stdout else ''
            raise RuntimeError(f'Zikra test server exited early: {output}')
        try:
            response = httpx.get(f'{base}/health', timeout=1)
            if response.status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.2)
    else:
        proc.terminate()
        output = proc.stdout.read() if proc.stdout else ''
        raise RuntimeError(f'Zikra test server did not become ready: {output}')

    yield {'process': proc, 'base': base}
    proc.terminate()
    proc.wait(timeout=5)
    if os.path.exists(db_path):
        os.unlink(db_path)


def _create_token(server, label: str, role: str = 'developer') -> str:
    response = httpx.post(
        f'{server["base"]}/webhook/zikra',
        headers={'Authorization': f'Bearer {OWNER_TOKEN}', 'Content-Type': 'application/json'},
        json={'command': 'create_token', 'label': label, 'role': role},
        timeout=10,
    )
    data = response.json()
    assert 'token' in data, f'create_token failed: {data}'
    return data['token']


class TestUsersEndpoint:
    def test_returns_200_without_auth(self, server):
        response = httpx.get(f'{server["base"]}/api/ui/users', timeout=10)
        assert response.status_code == 200

    def test_returns_json_array(self, server):
        response = httpx.get(f'{server["base"]}/api/ui/users', timeout=10)
        assert isinstance(response.json(), list)

    def test_label_key_present(self, server):
        _create_token(server, 'alice')
        data = httpx.get(f'{server["base"]}/api/ui/users', timeout=10).json()
        assert data
        for item in data:
            assert 'label' in item
            assert 'token' not in item

    def test_excludes_owner_role(self, server):
        data = httpx.get(f'{server["base"]}/api/ui/users', timeout=10).json()
        assert 'alice' in [item['label'] for item in data]

    def test_returns_created_non_owner_tokens(self, server):
        _create_token(server, 'bob')
        data = httpx.get(f'{server["base"]}/api/ui/users', timeout=10).json()
        assert 'bob' in [item['label'] for item in data]

    def test_no_auth_required(self, server):
        response = httpx.get(f'{server["base"]}/api/ui/users', timeout=10)
        assert response.status_code not in (401, 403)
