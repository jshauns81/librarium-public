"""Disposable source-browser network, credential, API and native sandbox proof. No provider traffic."""

import argparse
import copy
import json
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def acceptance(image, browser_image):
    layers = subprocess.check_output(
        ["docker", "image", "inspect", "--format", "{{json .RootFS.Layers}}", browser_image],
        text=True,
    )
    if len(json.loads(layers)) != 1:
        raise AssertionError("The distributed browser must contain one sanitized filesystem layer")
    with tempfile.TemporaryDirectory(prefix="librarium-installed-stack-") as directory:
        stack = Path(directory)
        for relative in (
            "compose.registry.yaml",
            "compose.cover-sources.yaml",
            "compose.source-browser.yaml",
            "services/source-browser/seccomp.json",
        ):
            target = stack / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)
        installed_acceptance(image, browser_image, stack)


def installed_acceptance(image, browser_image, stack):
    from scripts.registry_config import check

    name = "librarium-browser-proof-" + uuid.uuid4().hex[:10]
    env = {
        **os.environ,
        "LIBRARIUM_IMAGE": "ghcr.io/jshauns81/librarium-public@sha256:" + "a" * 64,
        "LIBRARIUM_SOURCE_BROWSER_IMAGE": "ghcr.io/jshauns81/librarium-public-source-browser@sha256:"
        + "b" * 64,
        "LIBRARIUM_PROJECT_NAME": name,
        "LIBRARIUM_DB_PASSWORD": uuid.uuid4().hex,
        "LIBRARIUM_SECRET_KEY": uuid.uuid4().hex * 2,
        "LIBRARIUM_PUBLIC_ORIGIN": "https://lib.example.org",
        "LIBRARIUM_DATA_ROOT": "/tmp/unused-browser-proof",
        "LIBRARIUM_EDGE_NETWORK": name + "-edge",
        "LIBRARIUM_COVER_SOURCES_SECRET": uuid.uuid4().hex * 2,
        "LIBRARIUM_SOURCE_BROWSER_SECRET": uuid.uuid4().hex * 2,
    }
    command = [
        "docker",
        "compose",
        "--env-file",
        "/dev/null",
        "--project-name",
        name,
        "--project-directory",
        str(stack),
    ]
    resolved = subprocess.run(
        command
        + [
            "-f",
            str(stack / "compose.registry.yaml"),
            "-f",
            str(stack / "compose.cover-sources.yaml"),
            "-f",
            str(stack / "compose.source-browser.yaml"),
            "--profile",
            "cover-sources",
            "--profile",
            "source-browser",
            "config",
            "--format",
            "json",
        ],
        env=env,
        cwd=stack,
        capture_output=True,
        check=True,
    )
    original = json.loads(resolved.stdout)
    check(original)
    model = copy.deepcopy(original)
    model["services"] = {
        k: v
        for k, v in model["services"].items()
        if k in {"web", "worker", "source-browser"}
    }
    for role, service in model["services"].items():
        for key in ("depends_on", "healthcheck", "profiles"):
            service.pop(key, None)
        service.update(
            restart="no",
            pull_policy="never",
            image=browser_image if role == "source-browser" else image,
        )
        if role != "source-browser":
            service["volumes"] = []
            service["command"] = ["python", "-c", "import time; time.sleep(300)"]
        else:
            service["networks"]["cover-egress"]["aliases"] = ["browser-egress-proof"]
    model["networks"] = {
        k: v
        for k, v in model["networks"].items()
        if k
        in {
            "default",
            "edge",
            "cover-control",
            "source-browser-control",
            "cover-egress",
        }
    }
    listener = "import socket; s=socket.socket(); s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1); s.bind(('0.0.0.0',8125)); s.listen(); exec('while True:\\n c,a=s.accept(); c.sendall(b\\\"proof\\\"); c.close()')"
    for host, network in (("db", "default"), ("egress-proof", "cover-egress")):
        model["services"][host] = {
            "image": image,
            "pull_policy": "never",
            "user": "10001:10001",
            "read_only": True,
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges:true"],
            "command": ["python", "-c", listener],
            "networks": {network: {}},
            "mem_limit": "128m",
            "pids_limit": 16,
        }
    with tempfile.TemporaryDirectory(prefix=name) as directory:
        entry = Path(directory) / "compose.json"
        entry.write_text(json.dumps(model))
        entry.chmod(0o600)
        prefix = command + ["-f", str(entry)]

        def run(args, script=None):
            result = subprocess.run(
                prefix + args,
                input=script,
                text=True,
                capture_output=True,
                env=env,
                cwd=stack,
                timeout=100,
                check=False,
            )
            if result.returncode:
                raise AssertionError(
                    "Disposable source-browser proof failed: "
                    + result.stderr[-1200:]
                    + subprocess.run(
                        prefix + ["logs", "--no-log-prefix", "source-browser"],
                        env=env,
                        cwd=stack,
                        capture_output=True,
                        text=True,
                        check=False,
                    ).stdout[-1200:]
                )
            return result.stdout

        try:
            profile = stack / "services/source-browser/seccomp.json"
            profile.rename(profile.with_suffix(".hidden"))
            try:
                missing = subprocess.run(
                    prefix + ["create", "--no-build", "source-browser"],
                    env=env,
                    cwd=stack,
                    capture_output=True,
                    timeout=30,
                    check=False,
                )
                assert missing.returncode != 0, (
                    "Missing installed seccomp profile was accepted"
                )
            finally:
                profile.with_suffix(".hidden").rename(profile)
            run(["up", "-d", "--no-build"])
            run(
                ["exec", "-T", "source-browser", "python3", "-"],
                """from pathlib import Path
import sys
assert sys.version_info[:2] == (3,12)
assert not list(Path('/etc/ssh').glob('ssh_host_*')), 'Browser contains SSH host identity files'
for path in Path('/role/librarium').glob('*.py'):
    compile(path.read_bytes(), str(path), 'exec')
""",
            )
            for role in ("web", "worker", "source-browser"):
                run(
                    [
                        "exec",
                        "-T",
                        role,
                        "python3" if role == "source-browser" else "python",
                        "-",
                    ],
                    """import socket,time
allowed = """
                    + repr(role == "source-browser")
                    + """
for attempt in range(30):
    try:
        with socket.create_connection(('egress-proof',8125),timeout=.2) as s: reached=s.recv(5)==b'proof'
    except OSError: reached=False
    if reached or not allowed: break
    time.sleep(.1)
assert reached == allowed
""",
                )
            run(
                ["exec", "-T", "source-browser", "python3", "-"],
                """import os,socket
assert os.getuid() == 999
assert not any(k.startswith(('PG','CALIBRE_','LIBRARIUM_DELIVERY')) or k in {'LIBRARIUM_SECRET_KEY','LIBRARIUM_COVER_SOURCES_SECRET'} for k in os.environ)
assert not any(os.path.exists(p) for p in ('/library','/artifacts','/catalogue','/var/run/docker.sock'))
for host in ('db','web'):
    try: socket.getaddrinfo(host,5432)
    except OSError: pass
    else: raise AssertionError('Browser reached application lane')
""",
            )
            run(
                ["exec", "-T", "worker", "python", "-"],
                """import hashlib,hmac,http.client,json,os,time
raw=json.dumps({'url':'https://localhost/refused'}).encode(); stamp=str(int(time.time()))
key=os.environ['LIBRARIUM_SOURCE_BROWSER_SECRET']
signature=hmac.new(key.encode(), b'POST\\n/goodreads\\n'+stamp.encode()+b'\\n'+raw, hashlib.sha256).hexdigest()
for attempt in range(30):
    try:
        for supplied, expected in [('',403),('0'*64,403),(signature,422)]:
            c=http.client.HTTPConnection('source-browser',8126,timeout=3)
            c.request('POST','/goodreads',raw,{'Content-Type':'application/json','X-Source-Time':stamp,'X-Source-Signature':supplied})
            r=c.getresponse(); assert r.status==expected; r.read(); c.close()
        break
    except ConnectionError: time.sleep(.1)
else: raise AssertionError('Browser control unavailable')
""",
            )
            run(
                ["exec", "-T", "egress-proof", "python", "-"],
                """import socket
try: socket.create_connection(('browser-egress-proof',8126),timeout=.5).close()
except OSError: pass
else: raise AssertionError('Control listener exposed on egress')
""",
            )
            sandbox = run(
                [
                    "exec",
                    "-T",
                    "source-browser",
                    "/usr/bin/xvfb-run",
                    "-a",
                    "node",
                    "-",
                ],
                """const {launch,loadPage}=require('/role/browser.cjs');
(async()=>{const b=await launch();try { const p=await b.newPage(); await p.goto('chrome://sandbox');
const text=await p.evaluate(()=>document.body.innerText);
if (!/Layer 1 Sandbox\\s+Namespace/.test(text) || !/Seccomp-BPF sandbox\\s+Yes/.test(text) || b.process().spawnargs.some(x=>x.includes('no-sandbox'))) throw Error('Native Chrome sandbox absent');
console.log('PASS: headed Chrome namespace and Seccomp-BPF sandboxes');
const url='https://wh40k.lexicanum.com/wiki/Novel';
const q=await b.newPage(); q.url=()=>url;
q.goto=async target=>{
 if(target===url) await q.setContent('<div id="mw-content-text"><table><tr><td><a class="image"><img src="/mediawiki/images/thumb/7/7e/Book2.jpg/60px-Book2.jpg"></a></td></tr><tr><td><a class="image"><img src="/mediawiki/images/thumb/a/ab/Novel.jpg/220px-Novel.jpg"></a></td></tr><tr><th>Author</th><td>Example Writer</td></tr></table></div>');
 return {status:()=>200,headers:()=>({}),text:async()=>'<mediawiki>fixture</mediawiki>'};
};
const result=await loadPage({url,kind:'lexicanum',wikis:['wh40k.lexicanum.com'],images:[],namespaces:['special','file','user']},q);
if(result.state!=='ok' || result.cover_url!=='https://wh40k.lexicanum.com/mediawiki/images/a/ab/Novel.jpg') throw Error('Portal placeholder selected before original cover');
console.log('PASS: offline real-browser infobox skips the portal placeholder');
} finally {await b.close();}})().catch(error=>{console.error(error.message);process.exitCode=1;});
""",
            )
            print(sandbox.strip())
            print(
                "PASS: installed stack seccomp profile required and used without a checkout; copied role modules compile on Python 3.12"
            )
            print(
                "PASS: resolved overlay admitted; browser-only egress; no application mounts or credentials; HMAC control restricted to internal lane"
            )
        finally:
            subprocess.run(
                prefix + ["down", "--volumes", "--remove-orphans"],
                env=env,
                cwd=stack,
                capture_output=True,
                check=True,
            )


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(ROOT))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--browser-image", required=True)
    args = parser.parse_args()
    acceptance(args.image, args.browser_image)
