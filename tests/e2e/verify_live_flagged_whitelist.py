"""Opt-in production Registry/CDN verification; never collected by pytest.

Requires E2E_ROOT with comfyui/ and venv/bin/python, as for the local E2E suite.
Pass two explicitly chosen ID@version values via --listed and --unlisted, and a
new --output directory. Both versions must currently be Flagged. The listed
archive must have no install.py or requirements.txt. Servers use isolated data
directories, the normal installation path, and do not reload installed nodes.
"""

import argparse
import hashlib
import json
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import requests
import test_e2e_flagged_nodepacks as harness

REGISTRY = 'https://api.comfy.org'


def get_json(path, **params):
    response = requests.get(REGISTRY + path, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--listed', required=True, metavar='ID@VERSION')
    parser.add_argument('--unlisted', required=True, metavar='ID@VERSION')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if not (harness.E2E_ROOT / 'venv/bin/python').is_file():
        parser.error('E2E_ROOT must point to the ComfyUI + venv fixture')
    packs = []
    for value in (args.listed, args.unlisted):
        node, separator, version = value.rpartition('@')
        if not node or not separator or not version:
            parser.error('Specify each pack as ID@VERSION')
        catalog = get_json('/nodes/' + quote(node, safe=''))
        assert catalog['id'] == node, catalog
        packs.append((catalog, version))
    assert packs[0][0]['id'].lower() != packs[1][0]['id'].lower(), 'Choose two different packs'
    output = args.output.resolve()
    output.mkdir(parents=True)
    catalog = {'nodes': [pack for pack, _ in packs], 'totalPages': 1}
    catalog_path = output / 'catalog.json'
    catalog_path.write_text(json.dumps(catalog, indent=2), encoding='utf-8')
    # Seed only the catalog cache from live /nodes/{id} responses. Installation
    # metadata and ZIP downloads still go directly to the production services.
    registry = SimpleNamespace(url=REGISTRY, catalog_url=catalog_path.as_uri())
    results = []

    def check(server, label, pack, version, allowed):
        node = pack['id']
        metadata = get_json('/nodes/' + quote(node, safe='') + '/install', version=version)
        assert metadata['status'] == 'NodeVersionStatusFlagged', metadata
        assert metadata['node_id'] == node and metadata['version'] == version, metadata
        expected = {}
        if allowed:
            response = requests.get(metadata['downloadUrl'], timeout=60)
            response.raise_for_status()
            archive_path = server.root / 'cdn.zip'
            archive_path.write_bytes(response.content)
            with zipfile.ZipFile(archive_path) as archive:
                assert 'install.py' not in archive.namelist(), 'Choose a pack without an install script'
                assert 'requirements.txt' not in archive.namelist(), 'Choose a pack without pip requirements'
                for member in archive.infolist():
                    if not member.is_dir():
                        expected[member.filename] = hashlib.sha256(archive.read(member)).hexdigest()
            assert expected, 'CDN archive is empty'
        log_path = server.root / 'server.log'
        offset = len(log_path.read_text())
        queue = harness.install(server, node, version, repository=pack['repository'])
        installed = server.root / 'custom_nodes' / node
        assert installed.exists() is allowed, queue
        if allowed:
            if server.tree == 'legacy':
                assert list(queue['nodepack_result'].values()) == ['success'], queue
            else:
                assert queue['history']['result'] == 'success', queue
            for name, digest in expected.items():
                assert hashlib.sha256((installed / name).read_bytes()).hexdigest() == digest, name
            assert (installed / '.tracking').is_file()
        else:
            harness.assert_flagged_denial(queue, log_path.read_text()[offset:])
            assert not any(installed.parent.glob('CNR_temp_*'))
        results.append({'tree': server.tree, 'label': label,
                        'observed_at': datetime.now(timezone.utc).isoformat(),
                        'registry_response': metadata, 'queue_response': queue,
                        'installed': installed.exists(), 'matched_archive_files': expected})
        (output / 'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
        print(f'{server.tree} {label}: installed={installed.exists()}, verified_files={len(expected)}', flush=True)

    for tree in ('glob', 'legacy'):
        root = output / tree
        root.mkdir()
        with harness.running_server(root, tree, '0.0.0.0', False, 'normal', registry) as server:
            whitelist = root / 'user/__manager/nodepack-whitelist.list'
            template = whitelist.read_text()
            assert template.strip() and all(line.lstrip().startswith('#') for line in template.splitlines() if line.strip())
            listed, version = packs[0]
            check(server, 'default-template', listed, version, False)
            whitelist.write_text(listed['id'].swapcase() + '\n', encoding='utf-8')
            check(server, 'listed-different-case', listed, version, True)
            check(server, 'unlisted-control', *packs[1], False)

    manifest = {
        'tested_commit': subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=harness.REPO_ROOT, text=True).strip(),
        'completed_cases': len(results), 'registry': REGISTRY,
        'archive_sha256': {str(path.relative_to(output)): hashlib.sha256(path.read_bytes()).hexdigest()
                           for path in output.glob('*/cdn.zip')},
    }
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(f'PASS: {len(results)} live Registry cases; evidence: {output}', flush=True)


if __name__ == '__main__':
    main()
