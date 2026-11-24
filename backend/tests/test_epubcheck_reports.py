"""Checker reports stay bounded and readable for synthetic publications."""

import hashlib

import pytest
from epub_members import encode_members, logical
from librarium.epubcheck_process import VALIDATION_POLICY, VALIDATOR_IDENTITY, validate_isolated
from test_epubcheck_native import publication, runtime  # noqa: F401


def digest(data):
    return hashlib.sha256(data).hexdigest()


@pytest.mark.usefixtures("runtime")
def test_valid_image_larger_than_report_budget_is_not_reported_corrupt():
    import random
    import struct
    import zlib

    def chunk(kind, body):
        return (
            struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
        )

    width, height = 1024, 512
    random_bytes = random.Random(0).randbytes(width * height * 3)
    scanlines = b"".join(
        b"\0" + random_bytes[i : i + width * 3] for i in range(0, len(random_bytes), width * 3)
    )
    image = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(scanlines))
        + chunk(b"IEND", b"")
    )
    assert len(image) > VALIDATION_POLICY["limits"]["max_report_bytes"]
    members = logical(publication())
    members["pixel.png"] = image
    members["book.opf"] = members["book.opf"].replace(
        b"</manifest>", b'<item id="pixel" href="pixel.png" media-type="image/png"/></manifest>'
    )
    members["chapter.xhtml"] = members["chapter.xhtml"].replace(
        b"</body>", b'<p><img src="pixel.png" alt="Synthetic test pixels"/></p></body>'
    )
    data = encode_members(members, list(members))
    report = validate_isolated(data, digest(data), VALIDATION_POLICY, VALIDATOR_IDENTITY)
    assert report["outcome"] == "passed", report["messages"]


def test_old_checker_reports_remain_readable_but_cannot_launch_the_old_profile():
    from copy import deepcopy

    from librarium.epub_validations import ValidationError, validate_report
    from librarium.epubcheck_process import ValidationProcessError
    from test_epub_validations import fake_report

    data = b"synthetic captured bytes"
    old_policy = deepcopy(VALIDATION_POLICY)
    old_policy["version"] = "librarium.epub-validation.v1"
    del old_policy["limits"]["max_scratch_file_bytes"]
    old_report = fake_report(data, digest(data), old_policy, VALIDATOR_IDENTITY)
    validate_report(
        old_report,
        sha256=digest(data),
        size=len(data),
        policy=old_policy,
        validator=VALIDATOR_IDENTITY,
    )
    with pytest.raises(ValidationError):
        validate_report(
            old_report,
            sha256=digest(data),
            size=len(data),
            policy=VALIDATION_POLICY,
            validator=VALIDATOR_IDENTITY,
        )
    with pytest.raises(ValidationProcessError) as error:
        validate_isolated(data, digest(data), old_policy, VALIDATOR_IDENTITY)
    assert error.value.code == "invalid_profile"
