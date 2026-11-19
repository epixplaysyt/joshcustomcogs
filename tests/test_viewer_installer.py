import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'modmailerviewer/scripts/install-nginx.sh'


def run(*args):
    return subprocess.run(['bash', str(SCRIPT), *args], text=True, capture_output=True, timeout=10)


def test_installer_shell_syntax():
    subprocess.run(['bash', '-n', str(SCRIPT)], check=True)


def test_preview_needs_no_root_and_renders_private_upstream():
    result = run('--ip', '8.8.8.8', '--port', '9090', '--check')
    assert result.returncode == 0, result.stderr
    assert 'proxy_pass http://127.0.0.1:9090;' in result.stdout
    assert 'server_name 8.8.8.8;' in result.stdout
    assert 'proxy_set_header Host $host;' in result.stdout
    assert 'location /.well-known/acme-challenge/' in result.stdout
    assert 'listen 443 ssl;' in result.stdout
    assert result.stdout.count('access_log off;') == 2


@pytest.mark.parametrize('ip', ['127.0.0.1', '192.168.1.1', '10.0.0.1', '0.0.0.0', '224.0.0.1', '203.0.113.10', '::1', 'example.com', '8.8.8.8; touch /tmp/should-not-exist', '8.8.8.8\nserver {}'])
def test_invalid_ip_is_rejected_before_installation(ip):
    result = run('--ip', ip, '--check')
    assert result.returncode != 0 and 'server {' not in result.stdout


@pytest.mark.parametrize('port', ['80', '443', '65536', '-1', '08088', '8088;id', 'invalid'])
def test_invalid_port_is_rejected_before_installation(port):
    result = run('--ip', '8.8.8.8', '--port', port, '--check')
    assert result.returncode != 0 and 'server {' not in result.stdout


def test_unknown_flags_and_missing_values_are_rejected():
    assert run('--bogus').returncode != 0
    assert run('--ip').returncode != 0
    assert run('--help').returncode == 0
