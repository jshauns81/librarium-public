# Populated-upgrade baseline

This fixture supplies an earlier Librarium backend for the populated-upgrade rehearsal. It uses Django migration leaf `0005_epub_validation_jobs`, EPUB inspection policy `librarium.epub-structure.v5` and validation policy `librarium.epub-validation.v1`. The rehearsal migrates an empty database with this backend, creates synthetic jobs through the historical application, and checks the saved results before and after upgrading. It also restores the earlier database and artifacts and opens them with this backend again.

The `source/` directory holds text files with an extra `.fixture` suffix. [The manifest](manifest.json) lists their materialized paths, file modes and SHA-256 digests. The rehearsal checks the manifest and file bytes before use. [The synthetic data adapter](../../../scripts/upgrade_fixture.py) creates the sample catalogue and EPUB at run time.

## Source and build scope

The Python application modules, five migrations, Python version and dependency locks, native build helpers and EPUBCheck distribution manifest were copied from the same historical Librarium source revision. The fixture keeps the original inspection, worker, validation and report code, including its existing source attributions. The image recipe retains the Python base digest, native library build, checksum-pinned Temurin and EPUBCheck installation, runtime account and application entry point.

The rehearsal uses the health API and management commands. Its image recipe omits the frontend build stage and creates an empty static directory. The fixture also omits tests, demo seeding, the optional reference-import command and producer, project history, deployment configuration, library files and prebuilt images. The rehearsal exercises database and artifact compatibility for the selected backend policies. It does not reproduce a previously released image digest or test the historical user interface.
