#!/usr/bin/env python3
"""Build only explicitly listed source files in AWS CodeBuild, without local Docker."""

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import subprocess
import time
import zipfile

import boto3

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / 'cloud/builds.json'
SOURCES = {
    'agent': ('company-agent/agents', ['Dockerfile', 'pyproject.toml', 'uv.lock', 'main.py', 'analyst.py', 'cloud_mcp.py']),
    'mcp': ('alpha-vantage-mcp/mcp_server', ['Dockerfile', 'pyproject.toml', 'uv.lock', 'server.py', 'alpha_vantage.py',
                                         'financials.py', 'fixtures/ibm.json']),
}


def check_builds(codebuild, record):
    ids = [entry['id'] for entry in record['builds'].values()]
    builds = codebuild.batch_get_builds(ids=ids)['builds']
    if len(ids) != 2 or {build['id'] for build in builds} != set(ids):
        raise RuntimeError('Expected both recorded builds; one or more builds are missing.')
    for build in builds:
        print(json.dumps({'project': build['projectName'], 'status': build['buildStatus'],
                          'phase': build.get('currentPhase'),
                          'logs': build.get('logs', {}).get('deepLink')}), flush=True)
    failed = [build for build in builds if build['buildStatus'] not in ('SUCCEEDED', 'IN_PROGRESS')]
    if failed:
        raise RuntimeError('Image build failed. Inspect the CodeBuild log links above before deploying.')
    return all(build['buildStatus'] == 'SUCCEEDED' for build in builds)


def wait_for_builds(codebuild, record, wait):
    deadline = time.monotonic() + 35 * 60
    while True:
        if check_builds(codebuild, record):
            print(f'Both builds succeeded. Set container_tag = "{record["tag"]}" in both infra/terraform.tfvars files.')
            return
        if not wait:
            print('Builds are still running. Use status --wait to wait for completion.')
            return
        if time.monotonic() >= deadline:
            raise RuntimeError('Timed out waiting for image builds. Run status to inspect them.')
        time.sleep(15)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'status'])
    parser.add_argument('--profile', help='AWS profile (otherwise use the standard AWS credential chain)')
    parser.add_argument('--wait', action='store_true', help='Wait for both builds; exit nonzero on failure')
    args = parser.parse_args()
    outputs = json.loads(subprocess.check_output(['terraform', f'-chdir={ROOT / "cloud/build"}', 'output', '-json']))
    session = boto3.Session(profile_name=args.profile, region_name=outputs['region']['value'])
    codebuild = session.client('codebuild')
    if args.action == 'status':
        record = json.loads(RECORD.read_text())
        wait_for_builds(codebuild, record, args.wait)
        return
    bucket = outputs['bucket']['value']
    record = {'tag': datetime.now(timezone.utc).strftime('cloud-%Y%m%d%H%M%S'), 'builds': {}}
    for kind, (folder, files) in SOURCES.items():
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
            for name in files:
                bundle.write(ROOT / folder / name, name)
        payload = archive.getvalue()
        key = f'sources/{kind}-{record["tag"]}.zip'
        session.client('s3').put_object(Bucket=bucket, Key=key, Body=payload, ServerSideEncryption='AES256')
        build = codebuild.start_build(projectName=outputs['projects']['value'][kind],
                                     sourceLocationOverride=f'{bucket}/{key}',
                                     environmentVariablesOverride=[{'name':'IMAGE_TAG','value':record['tag'],'type':'PLAINTEXT'}])['build']
        record['builds'][kind] = {'id':build['id'], 'source_sha256':hashlib.sha256(payload).hexdigest(), 'files':files}
        RECORD.write_text(json.dumps(record, indent=2)+'\n')
        print(json.dumps({'project':build['projectName'],'id':build['id'],'tag':record['tag'],'files':len(files)}))
    if args.wait:
        wait_for_builds(codebuild, record, True)


if __name__ == '__main__':
    main()
