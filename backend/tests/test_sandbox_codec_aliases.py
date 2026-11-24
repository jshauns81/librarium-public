"""A frozen codec registry must preserve the stdlib's alias normalization."""

import encodings.aliases
import json
import subprocess
import sys


def test_frozen_codec_registry_matches_stdlib_aliases():
    names = list(encodings.aliases.aliases) + list(encodings.aliases.aliases.values())
    names = sorted(set(names + [name.replace("_", ".") for name in names] + ["x-no-such-codec"]))
    script = """import sys,codecs,json
sys.path.insert(0,"backend")
if sys.argv[1]=="sandbox":
    from librarium.python_sandbox import restrict
    restrict()
results=[]
for name in json.loads(sys.stdin.read()):
    try: results.append(codecs.lookup(name).name)
    except LookupError: results.append(None)
print(json.dumps(results))
"""
    results = [
        json.loads(
            subprocess.check_output(
                [sys.executable, "-I", "-B", "-c", script, mode],
                input=json.dumps(names).encode(),
                timeout=5,
            )
        )
        for mode in ["plain", "sandbox"]
    ]
    assert results[0] == results[1]
