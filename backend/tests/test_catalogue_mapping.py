import hashlib
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import pytest
from librarium import catalogue


@pytest.mark.skipif(sys.platform != "linux", reason="Packaged Linux reader I/O regression")
def test_immutable_catalogue_scan_avoids_per_page_read_syscalls(tmp_path):
    path = tmp_path / "large.sqlite"
    payload = "x" * 16384
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE evidence (id INTEGER PRIMARY KEY, payload TEXT)")
        db.executemany("INSERT INTO evidence(payload) VALUES (?)", [(payload,)] * 512)
    before_hash = hashlib.sha256(path.read_bytes()).hexdigest()

    def reads():
        values = dict(line.split(": ") for line in Path("/proc/self/io").read_text().splitlines())
        return int(values["syscr"])

    with catalogue.connection(path) as db:
        before = reads()
        rows = list(db.execute("SELECT payload FROM evidence ORDER BY id DESC"))
        read_calls = reads() - before
        assert len(rows) == 512 and all(row[0] == payload for row in rows)
        assert read_calls < 64, f"Immutable scan issued {read_calls} file-read syscalls"
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            db.execute("UPDATE evidence SET payload='changed'")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before_hash
