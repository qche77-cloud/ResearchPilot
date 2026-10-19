"""Check the Git index before publishing, without logging secret values.

Scans the complete staged tree for private paths, key signatures and exact local
credential values. This is a practical guard, not a general secret certification.
Does not connect to any service or alter Git, environment files or databases.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def local_credentials():
    candidates = dict(os.environ)
    local = ROOT / '.env'
    if local.is_file():
        for line in local.read_text(encoding='utf-8-sig').splitlines():
            match = re.match(r'^\s*(?:export\s+)?([A-Za-z_][A-Za-z_0-9]*)\s*=\s*(.*?)\s*$', line)
            if match:
                candidates[match[1]] = match[2].strip().strip('\"\'')
    return [v.encode('utf-8') for k, v in candidates.items()
            if re.search(r'(API_KEY|TOKEN|SECRET|PASSWORD)', k, re.I) and len(v) >= 12]


def scan():
    findings = []
    credentials = local_credentials()
    names = git('ls-files', '-z').decode('utf-8').split('\0')
    signatures = [
        rb'\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{24,}',
        rb'\btvly-[A-Za-z0-9_-]{20,}',
        rb'\bgh[pousr]_[A-Za-z0-9]{30,}',
        rb'\bgithub_pat_[A-Za-z0-9_]{30,}',
        rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
    ]
    count = 0
    for name in filter(None, names):
        # Deleted index paths are not in ls-files; all others read from index,
        # so unstaged edits cannot accidentally substitute for reviewed bytes.
        leaf = Path(name).name.lower()
        blocked = (leaf.startswith('.env') and leaf != '.env.example') or \
            leaf in {'secrets.toml', 'project.private.config.json'} or \
            bool(re.search(r'\.(?:db|sqlite|sqlite3|pem|key|pfx|p12)(?:-wal|-shm)?$', leaf)) or \
            (name.startswith('data/') and name != 'data/.gitkeep')
        if blocked:
            findings.append({'path': name, 'reason': 'private_file_path'})
            continue
        data = git('show', ':' + name)
        count += 1
        if any(secret in data for secret in credentials):
            findings.append({'path': name, 'reason': 'matches_local_credential_value'})
        if any(re.search(pattern, data) for pattern in signatures):
            findings.append({'path': name, 'reason': 'credential_signature'})
    return {'scope': 'complete_git_index', 'files_scanned': count,
            'secret_values_logged': False, 'findings': findings, 'passed': not findings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='artifacts/publish-safety-2026-10-20.json')
    args = parser.parse_args()
    result = scan()
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
