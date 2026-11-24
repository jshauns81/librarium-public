"""Validate the resolved overlay, then execute it with owned local network fixtures."""
import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[2]
SECRET = 'LIBRARIUM_COVER_SOURCES_SECRET'


def validate_model(model):
    services, networks = model['services'], model['networks']
    source = services['cover-sources']
    assert set(source['networks']) == {'cover-control', 'cover-egress'}
    assert not any(source.get(k) for k in ('volumes', 'ports', 'secrets', 'configs', 'env_file'))
    assert {'HARDCOVER_TOKEN', SECRET} <= set(source.get('environment', {})) <= {'HARDCOVER_TOKEN', 'GOOGLE_BOOKS_API_KEY', SECRET}
    assert all('GOOGLE_BOOKS_API_KEY' not in service.get('environment', {}) for role, service in services.items() if role != 'cover-sources')
    assert len(source['environment'][SECRET]) >= 32
    assert services['worker']['environment'][SECRET] == source['environment'][SECRET]
    assert SECRET not in services['web'].get('environment', {})
    assert set(services['worker']['networks']) == {'default', 'cover-control'}
    assert set(services['web']['networks']) == {'default', 'edge'}
    assert set(services['db']['networks']) == {'default'}
    for name in ('default', 'edge', 'cover-control'):
        assert networks[name].get('internal') is True
    assert not networks['cover-egress'].get('internal', False)


def acceptance(image):
    name = 'cover-proof-' + uuid.uuid4().hex[:12]
    env = {**os.environ, 'LIBRARIUM_IMAGE': image, 'LIBRARIUM_PROJECT_NAME': name,
           'LIBRARIUM_DB_PASSWORD': uuid.uuid4().hex, 'LIBRARIUM_SECRET_KEY': uuid.uuid4().hex*2,
           'LIBRARIUM_PUBLIC_ORIGIN': 'https://lib.example.org', 'LIBRARIUM_DATA_ROOT': '/tmp/unused-cover-proof',
           'LIBRARIUM_EDGE_NETWORK': name+'-edge', 'HARDCOVER_TOKEN': '', 'GOOGLE_BOOKS_API_KEY': 'fixture-google-key',
           SECRET: uuid.uuid4().hex*2, 'LIBRARIUM_COVER_SOURCES_ENABLED': 'true'}
    command = ['docker', 'compose', '--project-name', name]
    resolved = subprocess.run(command+['-f', str(ROOT/'compose.registry.yaml'), '-f', str(ROOT/'compose.cover-sources.yaml'), '--profile', 'cover-sources', 'config', '--format', 'json'], env=env, capture_output=True, check=True)
    original = json.loads(resolved.stdout)
    # These assertions see production facts before ANY fixture mutation.
    validate_model(original)
    model = copy.deepcopy(original)
    model['services'] = {k: v for k, v in model['services'].items() if k in ('web', 'worker', 'cover-sources')}
    for role, service in model['services'].items():
        for key in ('depends_on', 'healthcheck', 'profiles'):
            service.pop(key, None)
        service['restart'] = 'no'
        service['pull_policy'] = 'never'
        if role != 'cover-sources':
            service['volumes'] = []
            service['command'] = ['python', '-c', 'import time; time.sleep(300)']
    model['services']['cover-sources']['networks']['cover-egress'].setdefault('aliases', []).append('source-egress-proof')
    model['volumes'] = {}
    model['networks'] = {k: v for k, v in model['networks'].items() if k in ('default', 'edge', 'cover-control', 'cover-egress')}
    listener = "import socket; s=socket.socket(); s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1); s.bind(('0.0.0.0',8125)); s.listen(); exec('while True:\\n c,a=s.accept(); c.sendall(b\\\"proof\\\"); c.close()')"
    for host, network in [('db', 'default'), ('egress-proof', 'cover-egress'), ('ingress-proof', 'edge')]:
        model['services'][host] = {'image': image, 'pull_policy': 'never', 'user': '10001:10001', 'read_only': True, 'cap_drop': ['ALL'], 'security_opt': ['no-new-privileges:true'], 'command': ['python', '-c', listener], 'networks': {network: {}}, 'mem_limit': '128m', 'pids_limit': 16}
    with tempfile.TemporaryDirectory(prefix=name) as directory:
        entry = Path(directory)/'compose.json'
        entry.write_text(json.dumps(model)); entry.chmod(0o600)
        prefix = command+['-f', str(entry)]
        def run(args, script=None):
            result = subprocess.run(prefix+args, input=script, text=True, capture_output=True, env=env, timeout=100)
            if result.returncode:
                raise AssertionError('Disposable cover-role proof failed: '+result.stderr[-1500:])
            return result.stdout
        try:
            run(['up', '-d', '--no-build'])
            for role in ('web', 'worker', 'cover-sources'):
                run(['exec', '-T', role, 'python', '-'], '''import socket,time
allowed = '''+repr(role == 'cover-sources')+'''
for attempt in range(30):
    try:
        with socket.create_connection(('egress-proof',8125),timeout=.2) as s: reached=s.recv(5)==b'proof'
    except OSError: reached=False
    if reached or not allowed: break
    time.sleep(.1)
assert reached == allowed, 'local egress listener boundary'
''')
            run(['exec', '-T', 'web', 'python', '-'], '''import socket
with socket.create_connection(('ingress-proof',8125),timeout=3) as s: assert s.recv(5)==b'proof'
try: socket.getaddrinfo('cover-sources',8124)
except OSError: pass
else: raise AssertionError('Web reached source lane')
''')
            run(['exec', '-T', 'worker', 'python', '-'], '''import socket
with socket.create_connection(('db',8125),timeout=3) as s: assert s.recv(5)==b'proof'
''')
            run(['exec', '-T', 'cover-sources', 'python', '-'], '''import os,socket
assert not any(k.startswith(('PG','CALIBRE_','LIBRARIUM_DELIVERY','LIBRARIUM_DIRECT_LIBRARY')) or k=='LIBRARIUM_SECRET_KEY' for k in os.environ)
assert os.environ['GOOGLE_BOOKS_API_KEY'] == 'fixture-google-key'
assert not any(os.path.exists(p) for p in ('/library','/artifacts','/catalogue'))
for host in ('db','web'):
    try: socket.getaddrinfo(host,5432)
    except OSError: pass
    else: raise AssertionError('Source reached application network')
# The same container's egress address must not have a listening control socket.
ip=socket.gethostbyname(socket.gethostname())
control=socket.gethostbyname('cover-control-listener')
for answer in socket.getaddrinfo(socket.gethostname(),8124,type=socket.SOCK_STREAM):
    address=answer[4]
    if address[0]==control: continue
    try: socket.create_connection(address,timeout=.3).close()
    except OSError: pass
    else: raise AssertionError('Control listener exposed on egress')
''')
            run(['exec', '-T', 'worker', 'python', '-'], '''import http.client,json,time,os
assert 'GOOGLE_BOOKS_API_KEY' not in os.environ
body=json.dumps({'query':{'title':'Synthetic Novel','author':'Example Writer','isbn':''},'sources':['hardcover'],'request_id':'00000000-0000-4000-8000-000000000001'})
for attempt in range(30):
    try:
        for key, expected in [('',403),('wrong',403),(os.environ['LIBRARIUM_COVER_SOURCES_SECRET'],200)]:
            c=http.client.HTTPConnection('cover-sources',8124,timeout=5)
            c.request('POST','/search',body,{'Content-Type':'application/json','X-Cover-Control':key})
            r=c.getresponse(); assert r.status==expected
            if expected==200: assert json.load(r)=={'state':'not_configured','candidates':[]}
            else: r.read()
            c.close()
        break
    except ConnectionError: time.sleep(.1)
else: raise AssertionError('Typed source interface unavailable')
''')
            run(['exec', '-T', 'egress-proof', 'python', '-'], '''import socket
try: socket.create_connection(('source-egress-proof',8124),timeout=.5).close()
except OSError: pass
else: raise AssertionError('Source listener reachable from egress network')
''')
            lines = run(['logs', '--no-log-prefix', 'cover-sources']).splitlines()
            records = [json.loads(line) for line in lines if line.strip().startswith('{')]
            assert records and all(set(r) == {'source', 'state', 'count', 'duration_ms'} for r in records)
            assert any(r['source'] == 'hardcover' and r['state'] == 'not_configured' and r['count'] == 0 for r in records)
            assert all(term not in '\n'.join(lines) for term in ('Synthetic Novel', 'Example Writer', 'fixture-google-key', env[SECRET]))
            print('PASS: original model validated; local egress/ingress/DB network proof; authenticated control-only listener; no source mounts or application credentials')
        finally:
            subprocess.run(prefix+['down', '--volumes', '--remove-orphans'], env=env, capture_output=True, check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    acceptance(parser.parse_args().image)
