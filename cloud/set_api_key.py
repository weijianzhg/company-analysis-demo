#!/usr/bin/env python3
"""Store an Alpha Vantage key from a hidden prompt or dotenv file in Secrets Manager.

The key is never printed or passed as a command-line argument or Terraform value.
"""

import argparse
from getpass import getpass
from pathlib import Path
import subprocess

import boto3
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, help='Read ALPHA_VANTAGE_API_KEY from this file instead of prompting')
    parser.add_argument('--profile', help='AWS profile (otherwise use the standard AWS credential chain)')
    args = parser.parse_args()
    key = (dotenv_values(args.env_file).get('ALPHA_VANTAGE_API_KEY', '')
           if args.env_file else getpass('Alpha Vantage API key (hidden): '))
    key = (key or '').strip()
    if not key or key == 'demo':
        raise SystemExit('Supply a non-demo Alpha Vantage API key.')
    arn = subprocess.check_output(['terraform', f'-chdir={ROOT / "alpha-vantage-mcp/infra"}',
                                   'output', '-raw', 'alpha_vantage_secret_arn'], text=True).strip()
    boto3.Session(profile_name=args.profile, region_name=arn.split(':')[3]).client('secretsmanager').put_secret_value(
        SecretId=arn, SecretString=key)
    print('Alpha Vantage secret updated. Start a new runtime session or deploy a new runtime version to load it.')


if __name__ == '__main__':
    main()
