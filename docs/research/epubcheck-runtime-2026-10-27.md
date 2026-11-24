# EPUBCheck distribution and Java runtime, 2026-10-27

EPUBCheck **5.4.0** is W3C's current production release, published on
2026-09-15. The [official release](https://github.com/w3c/epubcheck/releases/tag/v5.4.0)
and [installation guide](https://www.w3.org/publishing/epubcheck/docs/installation/)
identify the complete ZIP distribution. Keep its `epubcheck.jar`, `lib/`, license
and notice files together; a single downloaded JAR is incomplete.

The [pinned manifest](../../backend/librarium/epubcheck_distribution.json)
records the official URL, archive SHA-256, all **40** JAR paths and hashes, their
combined manifest hash, version and required Java major. The
[installer](../../scripts/install_epubcheck.py) checks the complete archive before
opening it, extracts into a private staging directory, verifies the exact JAR set
and publishes the directory only after verification. Reuse verifies the existing
tree and refuses changes. The original `LICENSE.txt`, `THIRD-PARTY.txt` and
`licenses/` remain in the installation.

| Pin | Value |
| --- | --- |
| EPUBCheck archive | `https://github.com/w3c/epubcheck/releases/download/v5.4.0/epubcheck-5.4.0.zip` |
| Archive SHA-256 | `33350c61038e71dfb3d45a76aed04bf5481e6d5500cb780f6e98db8bbd15a28c` |
| JAR manifest SHA-256 | `06b5f9c5bf5d0a0c681ec10d3ae6daaa6340bc4a56bb9b968f1eafa96f8a1fcd` |
| Java major | `21` |

The manifest hash is SHA-256 over the UTF-8 bytes of
`json.dumps(jars, sort_keys=True, separators=(",", ":"))`. JAR paths are relative
to the installation root, including `epubcheck.jar` and each `lib/*.jar`.
The archive's published digest comes from the
[official release API](https://api.github.com/repos/w3c/epubcheck/releases/tags/v5.4.0);
the downloaded 33,093,170-byte ZIP matched it locally.

## Java 21 and the container

Java 21 remains supported through at least December 2029 under
[Adoptium's support roadmap](https://adoptium.net/support/).
The container pins **Eclipse Temurin 21.0.13+9**, the
[official October maintenance/security release](https://github.com/adoptium/temurin21-binaries/releases/tag/jdk-21.0.13%2B9).
The archive's `release` file identifies Java 21.0.13, dated 2026-10-20.

| Runtime pin | Value |
| --- | --- |
| Linux x64 JRE | `https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.13%2B9/OpenJDK21U-jre_x64_linux_hotspot_21.0.13_9.tar.gz` |
| JRE archive SHA-256 | `a535a1df9c6284d9618872984e026ae0352d1f7e9e0605425c0e6114f47351dd` |
| Container executable | `/opt/java/openjdk/bin/java` |
| EPUBCheck directory | `/opt/epubcheck` |

The [official Temurin release API](https://api.github.com/repos/adoptium/temurin21-binaries/releases/tags/jdk-21.0.13%2B9)
publishes that asset digest; the 52,181,297-byte download matched it locally.
Docker verifies the digest with `ADD --checksum` before unpacking the JRE and
preserves its `legal/` directory. It uses the existing pinned Python bookworm
base and signed Debian snapshot `20261027T000000Z` for `libseccomp2`, `fontconfig`
and certificates. There is no floating Java or EPUBCheck download in the build.
The two explicit application settings are `LIBRARIUM_EPUBCHECK_DIR=/opt/epubcheck`
and `LIBRARIUM_JAVA=/opt/java/openjdk/bin/java`.

The build requires `linux/amd64`. Existing [packaging requirements](../packaging.md) do not promise ARM
images; [container acceptance](../../.github/workflows/container.yml) builds
natively on `ubuntu-24.04`. Adding a platform requires its own official runtime
pin and actual image acceptance.

## Verification and upgrades

Verify the complete JAR manifest and run `java -jar epubcheck.jar --version` using the pinned JRE. A synthetic EPUB with missing modified metadata completed
with exit 1 and an `RSC-005` conformance error in `book.opf`. Its JSON checker
included `nFatal`, `nError`, `nWarning` and `nUsage`; no aggregate `nInfo` field
was present. Adding valid modified metadata and changing the identifier to
`urn:uuid:bogus` produced a genuine warning-only result: exit 0, no errors,
one `OPF-085` warning at `book.opf`. Unlisted `.txt` and `.xhtml` files did not
produce a warning in these minimal fixtures.

The **34** installer and acceptance-helper tests passed, including corrupt
downloads, complete JAR bindings, unsafe archive entries, request headers/status
and saved source/report bindings. Ruff checks/format and the installer's isolated
mypy check passed. Local checks do not
establish an image build, container replacement or database/artifact restore
result; exact-head CI remains the acceptance gate.

For an upgrade, review the official EPUBCheck and Temurin release/support pages,
download their exact assets, verify the publisher digests, rebuild the complete
JAR manifest and update the Docker checksum deliberately. Retain all licenses.
Update validator identity and processing policy together while preserving old
report identities. Recheck JSON fields, valid/invalid inputs, process bounds,
worker replacement and isolated database/artifact restore in the actual image
before publishing a compatible release. No production activation or library
write is part of this packaging work.
