"""Real HTTP on both sides, real Strands loop, fixture data and scripted model."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]
MCP_ROOT = Path(os.environ.get('MCP_REPO', ROOT.parent / 'alpha-vantage-mcp'))


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


@contextmanager
def service(command, cwd, env, port, log_path):
    with log_path.open('w+') as log:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    log.seek(0)
                    raise AssertionError(log.read())
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=0.2):
                        break
                except OSError:
                    time.sleep(0.05)
            else:
                raise AssertionError('Server startup timed out')
            yield
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def test_full_http_agent_mcp_roundtrip(tmp_path):
    mcp_port, agent_port = free_port(), free_port()
    env = dict(os.environ, ALPHA_VANTAGE_MODE='fixture', ALPHA_VANTAGE_API_KEY='',
               MCP_HOST='127.0.0.1', MCP_PORT=str(mcp_port),
               MCP_URL=f'http://127.0.0.1:{mcp_port}/mcp', AWS_EC2_METADATA_DISABLED='true')
    for name in ('MCP_RUNTIME_ARN', 'INTERNAL_KNOWLEDGE_MCP_RUNTIME_ARN', 'INTERNAL_KNOWLEDGE_MCP_URL'):
        env.pop(name, None)
    mcp_python = MCP_ROOT / 'mcp_server/.venv/bin/python'
    assert mcp_python.exists(), 'Run uv sync --project ../alpha-vantage-mcp/mcp_server --dev first'
    # Model injection exists only in this test process, not in the production app.
    agent_code = ('import main, analyst; from scripted_model import ScriptedModel; '
                  'main.analyze = lambda prompt, **kwargs: analyst.analyze(prompt, model=ScriptedModel(), **kwargs); '
                  f'main.app.run(host="127.0.0.1", port={agent_port})')
    agent_env = dict(env, PYTHONPATH=os.pathsep.join([str(ROOT / 'agents'), str(ROOT / 'tests')]))
    with service([str(mcp_python), 'mcp_server/server.py'], MCP_ROOT, env, mcp_port, tmp_path/'mcp.log'):
        with service([sys.executable, '-c', agent_code], ROOT, agent_env, agent_port, tmp_path/'agent.log'):
            response = httpx.post(f'http://127.0.0.1:{agent_port}/invocations',
                                  json={'prompt': "Analyze IBM's P&L and P/E"}, timeout=45)
            assert response.status_code == 200
            events = [json.loads(line[5:]) for line in response.text.splitlines() if line.startswith('data:')]
            assert events[0]['type'] == 'heartbeat'
            progress = [event for event in events if event.get('type') == 'tool_call']
            assert [event['status'] for event in progress] == ['started', 'succeeded']
            assert all(event['tool'] == 'get_company_snapshot' and event['server'] == 'financials' for event in progress)
            final = events[-1]
            assert final['tools_used'] == ['get_company_snapshot']
            assert 'SCRIPTED TEST MODEL / SYNTHETIC TEST DATA' in final['result']
            assert 'revenue growth 10.0%' in final['result']
            assert 'net margin 15.0%' in final['result']
            assert 'P/E 20.0' in final['result']
            cli = subprocess.run([sys.executable, 'scripts/ask.py', 'Analyze IBM', '--url',
                                  f'http://127.0.0.1:{agent_port}/invocations'], cwd=ROOT,
                                 capture_output=True, text=True, timeout=45)
            assert cli.returncode == 0, cli.stderr
            assert 'SYNTHETIC TEST DATA' in cli.stdout
            assert '[financials] get_company_snapshot: started' in cli.stderr
            assert '[financials] get_company_snapshot: succeeded' in cli.stderr
            if os.environ.get('EVIDENCE_DIR'):
                path = Path(os.environ['EVIDENCE_DIR'])
                path.mkdir(parents=True, exist_ok=True)
                (path/'fixture-e2e.json').write_text(json.dumps(final, indent=2)+'\n')


def test_agent_uses_both_mcp_servers_in_one_analysis(tmp_path, monkeypatch):
    from contextlib import ExitStack
    from analyst import analyze
    from scripted_model import MultiSourceModel

    knowledge_root = ROOT.parent / 'internal-knowledge-mcp'
    financial_port, knowledge_port = free_port(), free_port()
    monkeypatch.delenv('MCP_RUNTIME_ARN', raising=False)
    monkeypatch.delenv('INTERNAL_KNOWLEDGE_MCP_RUNTIME_ARN', raising=False)
    monkeypatch.setenv('MCP_URL', f'http://127.0.0.1:{financial_port}/mcp')
    monkeypatch.setenv('INTERNAL_KNOWLEDGE_MCP_URL', f'http://127.0.0.1:{knowledge_port}/mcp')
    env = dict(os.environ, ALPHA_VANTAGE_MODE='fixture', ALPHA_VANTAGE_API_KEY='',
               MCP_HOST='127.0.0.1', AWS_EC2_METADATA_DISABLED='true')
    with ExitStack() as services:
        services.enter_context(service(
            [str(MCP_ROOT / 'mcp_server/.venv/bin/python'), 'mcp_server/server.py'],
            MCP_ROOT, dict(env, MCP_PORT=str(financial_port)), financial_port, tmp_path / 'financial.log'))
        services.enter_context(service(
            [str(knowledge_root / 'mcp_server/.venv/bin/python'), 'tests/serve_fixture.py'],
            knowledge_root, dict(env, MCP_PORT=str(knowledge_port)), knowledge_port, tmp_path / 'knowledge.log'))
        progress = []
        result = analyze('Analyze IBM financials and our internal hybrid cloud research', model=MultiSourceModel(),
                         on_tool_event=progress.append)
        probe = subprocess.run(
            [sys.executable, 'scripts/probe_mcp.py', '--service', 'internal-knowledge',
             '--url', f'http://127.0.0.1:{knowledge_port}/mcp', '--path', 'companies/IBM/research.md'],
            cwd=ROOT, capture_output=True, text=True, timeout=30)
        assert probe.returncode == 0, probe.stderr
        assert json.loads(probe.stdout)['source'] == 's3://demo-knowledge/knowledge/companies/IBM/research.md'
    assert result['tools_used'] == ['get_company_snapshot', 'list_internal_documents',
                                    'search_internal_knowledge', 'read_internal_document']
    assert 'Revenue growth 10.0%' in result['result']
    assert 's3://demo-knowledge/knowledge/companies/IBM/research.md' in result['result']
    assert 'customer interview notes' in result['result']

    assert len(progress) == 8
    for start, end in zip(progress[::2], progress[1::2]):
        assert start['status'] == 'started' and end['status'] == 'succeeded'
        assert start['id'] == end['id']
    assert {event['server'] for event in progress} == {'financials', 'internal-knowledge'}
