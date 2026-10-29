"""Deployment helpers must fail closed on missing/failed builds and keep keys private."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

CLOUD = Path(__file__).resolve().parents[2] / 'cloud'


def load(name):
    spec = importlib.util.spec_from_file_location(name, CLOUD / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('statuses, expected', [
    (['SUCCEEDED', 'SUCCEEDED'], True),
    (['SUCCEEDED', 'IN_PROGRESS'], False),
    (['SUCCEEDED', 'FAILED'], RuntimeError),
    (['SUCCEEDED', 'STOPPED'], RuntimeError),
    (['SUCCEEDED'], RuntimeError),
])
def test_build_completion_requires_both_successes(statuses, expected):
    module = load('build_images')
    record = {'builds': {'agent': {'id': 'agent-id'}, 'mcp': {'id': 'mcp-id'}}}
    builds = [{'id': kind + '-id', 'projectName': kind, 'buildStatus': status}
              for kind, status in zip(('agent', 'mcp'), statuses)]
    codebuild = SimpleNamespace(batch_get_builds=lambda **kwargs: {'builds': builds})
    if expected is RuntimeError:
        with pytest.raises(RuntimeError):
            module.check_builds(codebuild, record)
    else:
        assert module.check_builds(codebuild, record) is expected


def test_secret_uses_arn_region_and_records_only_revision(monkeypatch, capsys, tmp_path):
    module = load('set_api_key')
    secret_arn = 'arn:aws:secretsmanager:us-west-2:123456789012:secret:test'
    calls = []
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    (tmp_path / 'alpha-vantage-mcp/infra').mkdir(parents=True)
    monkeypatch.setattr('sys.argv', ['set_api_key.py'])
    monkeypatch.setattr(module, 'getpass', lambda prompt: '  private-test-key  ')
    monkeypatch.setattr(module.subprocess, 'check_output', lambda *args, **kwargs: secret_arn)

    def session(**kwargs):
        calls.append(kwargs)
        def put_secret(**values):
            calls.append(values)
            return {'VersionId': 'test-version-id'}
        return SimpleNamespace(client=lambda service: SimpleNamespace(
            put_secret_value=put_secret))

    monkeypatch.setattr(module.boto3, 'Session', session)
    module.main()
    assert calls == [{'profile_name': None, 'region_name': 'us-west-2'},
                     {'SecretId': secret_arn, 'SecretString': 'private-test-key'}]
    assert 'private-test-key' not in capsys.readouterr().out
    revision_file = tmp_path / 'alpha-vantage-mcp/infra/secret-version.auto.tfvars.json'
    assert json.loads(revision_file.read_text()) == {'alpha_vantage_key_version': 'test-version-id'}


@pytest.mark.parametrize('key', ['', 'demo'])
def test_invalid_key_prevents_any_aws_call(monkeypatch, key):
    module = load('set_api_key')
    monkeypatch.setattr('sys.argv', ['set_api_key.py'])
    monkeypatch.setattr(module, 'getpass', lambda prompt: key)
    monkeypatch.setattr(module.subprocess, 'check_output', lambda *a, **k: pytest.fail('Must validate before AWS setup'))
    with pytest.raises(SystemExit, match='non-demo'):
        module.main()


def test_build_uses_terraform_region_and_only_explicit_sources(monkeypatch, tmp_path):
    module = load('build_images')
    calls, archives = [], []
    record = tmp_path / 'builds.json'
    monkeypatch.setattr(module, 'RECORD', record)
    monkeypatch.setattr('sys.argv', ['build_images.py', 'start'])
    monkeypatch.setattr(module.subprocess, 'check_output', lambda *a, **k: json.dumps({
        'region': {'value': 'us-west-2'}, 'bucket': {'value': 'test-bucket'},
        'projects': {'value': {'agent': 'agent-build', 'mcp': 'mcp-build'}},
    }).encode())

    def session(**kwargs):
        calls.append(kwargs)
        def start(**args):
            return {'build': {'id': args['projectName'] + '-id', 'projectName': args['projectName']}}
        return SimpleNamespace(client=lambda service: SimpleNamespace(
            put_object=lambda **args: archives.append(args['Body']), start_build=start))

    monkeypatch.setattr(module.boto3, 'Session', session)
    module.main()
    assert calls == [{'profile_name': None, 'region_name': 'us-west-2'}]
    assert len(archives) == 2
    for archive in archives:
        with module.zipfile.ZipFile(module.io.BytesIO(archive)) as bundle:
            assert 'Dockerfile' in bundle.namelist()
            assert not any('.env' in name or '.tfstate' in name or '.git' in name for name in bundle.namelist())
    assert set(json.loads(record.read_text())['builds']) == {'agent', 'mcp'}
