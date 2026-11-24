"""The inspection child preserves pre-sandbox encoding behavior."""

import hashlib

import pytest
from librarium import inspection_process
from librarium.epub_inspection import InspectionPolicy, inspect_bytes
from librarium.inspection_process import inspect_isolated
from sandbox_encoding_fixtures import fixtures


@pytest.fixture(params=[False, True], ids=["normal_threads", "no_threads"])
def thread_policy(request, tmp_path, monkeypatch):
    if not request.param:
        return
    child = tmp_path / "inspection_process.py"
    child.write_text(f"""import sys,ctypes
sys.path.insert(0,{str(inspection_process.__file__.rsplit("/", 2)[0])!r})
from librarium import python_sandbox
original=python_sandbox.restrict
libc=ctypes.CDLL(None,use_errno=True)
class Filter(ctypes.Structure):
    _fields_=[("code",ctypes.c_ushort),("jt",ctypes.c_ubyte),("jf",ctypes.c_ubyte),("k",ctypes.c_uint32)]
class Program(ctypes.Structure):
    _fields_=[("len",ctypes.c_ushort),("filter",ctypes.POINTER(Filter))]
# The production filter checks the architecture; this extra filter denies all clones.
filters=(Filter*5)(Filter(0x20,0,0,0),Filter(0x15,1,0,56),Filter(0x15,0,1,435),Filter(6,0,0,0x50001),Filter(6,0,0,0x7fff0000))
program=Program(5,filters)
def restrict():
    original()
    assert libc.prctl(22,2,ctypes.byref(program),0,0)==0
python_sandbox.restrict=restrict
from librarium import inspection_process as process
process._child()
""")
    monkeypatch.setattr(inspection_process, "_CHILD_PATH", child)


@pytest.mark.parametrize("name", fixtures)
def test_inspection_child_matches_unsandboxed_encoding_results(name, thread_policy):
    source = fixtures[name]
    report = inspect_bytes(source, hashlib.sha256(source).hexdigest())
    assert (
        inspect_isolated(source, hashlib.sha256(source).hexdigest(), InspectionPolicy()) == report
    )
