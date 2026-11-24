"""Read an EPUB into its logical members and write members back, for test fixtures only."""

import io
import zipfile
import zlib


def logical(data: bytes) -> dict[str, bytes]:
    from librarium.epub_archive import read_archive
    from librarium.epub_inspection import InspectionPolicy

    archive = read_archive(data, InspectionPolicy())
    return {path: archive.read(path) for path in archive.members}


def _stored(body: bytes, expansion_ratio: int = 200) -> bool:
    # Very compressible bodies are stored so the inspection's expansion-ratio limit still admits them.
    compressor = zlib.compressobj(6, zlib.DEFLATED, -15)
    size = len(compressor.compress(body)) + len(compressor.flush())
    return len(body) > max(1, size) * expansion_ratio


def encode_members(members: dict[str, bytes], order: list[str] | None = None) -> bytes:
    """A readable EPUB container: stored mimetype first, then members in the given order."""
    names = ["mimetype"] if "mimetype" in members else []
    names += [path for path in order or [] if path in members and path not in names]
    names += sorted(set(members) - set(names), key=lambda name: name.encode("utf-8"))
    assert names and names[0] == "mimetype"
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", allowZip64=False) as zipped:
        for path in names:
            info = zipfile.ZipInfo(path, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o600 << 16
            stored = path == "mimetype" or _stored(members[path])
            info.compress_type = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
            zipped.writestr(info, members[path])
    return output.getvalue()
