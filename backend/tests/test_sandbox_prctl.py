"""prctl's int option must be filtered using the same width as the kernel."""

import subprocess
import sys


def test_parent_death_signal_cannot_be_cleared_with_high_option_bits():
    script = """import sys,ctypes,errno
sys.path.insert(0,"backend")
from librarium.python_sandbox import restrict
libc=ctypes.CDLL(None,use_errno=True)
restrict()
result=libc.syscall(157,ctypes.c_ulong(0x100000001),0,0,0,0)
assert result==-1 and ctypes.get_errno()==errno.EPERM,(result,ctypes.get_errno())
"""
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", script],
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode()
