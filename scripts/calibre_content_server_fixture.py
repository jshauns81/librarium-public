"""Synthetic server fault probes; never used by the application launcher."""

import io
import os
import signal
import sys
from pathlib import Path


def main():
    from calibre.db import backend, cache
    from calibre.srv.standalone import main as serve

    root = Path(os.environ["LIBRARIUM_SERVER_FIXTURE_ROOT"])
    write = backend.write_stream_to_format_file
    plugins = cache.run_import_plugins

    def copy(stream, destination):
        if (root / "kill-arm").exists():

            class Probe(io.BytesIO):
                def read(self, size=-1):
                    if self.tell() >= 64:
                        (root / "copy-paused").write_text("copying")
                        signal.pause()
                    return super().read(64)

            stream = Probe(stream.read())
        return write(stream, destination)

    def transform(stream, fmt):
        path = plugins(stream, fmt)
        if (root / "transform-arm").exists():
            path = str(root / "transformed.epub")
            data = stream.read() if hasattr(stream, "read") else Path(stream).read_bytes()
            Path(path).write_bytes(bytes(data) + b"synthetic import transformation")
        return path

    backend.write_stream_to_format_file = copy
    cache.run_import_plugins = transform
    sys.argv = ["calibre-server", *sys.argv[1:]]
    serve()


if __name__ == "__main__":
    main()
