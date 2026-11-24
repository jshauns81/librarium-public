import uuid

from django.db import models
from django.db.models import Q


class Work(models.Model):
    id = models.CharField(primary_key=True, max_length=40)
    title = models.CharField(max_length=240, db_index=True)
    author = models.CharField(max_length=160)
    series = models.CharField(max_length=160)
    payload = models.JSONField()


class LibraryReconciliation(models.Model):
    request_key = models.UUIDField(primary_key=True, editable=False)
    catalogue_version = models.CharField(max_length=80)
    catalogue_sha256 = models.CharField(max_length=64)
    previous_key = models.UUIDField(null=True)
    report = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)


class Job(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Real jobs name a pinned catalogue work or immutable source digest in target_id.
    kind = models.CharField(max_length=20, default="synthetic")
    target_id = models.CharField(max_length=80, default="", blank=True)
    work = models.ForeignKey(Work, on_delete=models.PROTECT, null=True, blank=True)
    request_key = models.UUIDField(unique=True)
    input_fingerprint = models.CharField(max_length=64)
    input = models.JSONField()
    fixture_failure = models.BooleanField(default=False)
    state = models.CharField(max_length=20, default="queued", db_index=True)
    checkpoint = models.PositiveIntegerField(default=0)
    revision = models.PositiveIntegerField(default=1)
    attempts = models.PositiveIntegerField(default=0)
    lease_token = models.UUIDField(null=True)
    lease_until = models.DateTimeField(null=True)
    message = models.CharField(max_length=240, default="Waiting for an inspection worker")
    result = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["work"],
                condition=Q(state__in=["queued", "running"]),
                name="one_active_inspection_per_work",
            ),
            models.UniqueConstraint(
                fields=["kind", "target_id"],
                condition=Q(kind="catalogue", state__in=["queued", "running"]),
                name="one_active_catalogue_review_per_target",
            ),
            models.UniqueConstraint(
                fields=["kind", "target_id"],
                condition=Q(kind="epub", state__in=["queued", "running"]),
                name="one_active_epub_inspection_per_source",
            ),
            models.UniqueConstraint(
                fields=["kind", "target_id"],
                condition=Q(kind="epub_validation", state__in=["queued", "running"]),
                name="one_active_epub_validation_per_source",
            ),
            models.CheckConstraint(
                condition=Q(kind="synthetic", work__isnull=False)
                | (Q(kind="catalogue", work__isnull=True, fixture_failure=False) & ~Q(target_id=""))
                | Q(
                    kind__in=[
                        "epub",
                        "epub_validation",
                        "library_reconcile",
                        "book_assessment",
                        "epub_correction",
                        "output_validation",
                        "delivery_prepare",
                        "epub_delivery",
                        "delivery_reconcile",
                        "epub_undo",
                    ],
                    work__isnull=True,
                    fixture_failure=False,
                    target_id__regex=r"\A[a-f0-9]{64}\Z",
                ),
                name="job_kind_matches_target",
            ),
            models.UniqueConstraint(
                fields=["kind", "target_id"],
                condition=Q(
                    kind__in=["library_reconcile", "book_assessment"],
                    state__in=["queued", "running"],
                ),
                name="one_active_library_check_per_intent",
            ),
            models.UniqueConstraint(
                fields=["kind", "target_id"],
                condition=Q(
                    kind__in=["epub_correction", "output_validation"],
                    state__in=["queued", "running"],
                ),
                name="one_active_corrected_output_intent",
            ),
        ]
        constraints.append(
            models.UniqueConstraint(
                fields=["kind", "target_id"],
                condition=Q(
                    kind__in=[
                        "delivery_prepare",
                        "epub_delivery",
                        "delivery_reconcile",
                        "epub_undo",
                    ],
                    state__in=["queued", "running"],
                ),
                name="one_active_delivery_intent",
            )
        )
        indexes = [models.Index(fields=["kind", "target_id"], name="job_kind_target_idx")]


class CorrectedEpub(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    generation_job = models.OneToOneField(
        Job, on_delete=models.PROTECT, related_name="corrected_output"
    )
    source_job = models.ForeignKey(Job, on_delete=models.PROTECT, related_name="corrected_sources")
    source_sha256 = models.CharField(max_length=64)
    source_report_sha256 = models.CharField(max_length=64)
    output_sha256 = models.CharField(max_length=64)
    output_size = models.PositiveIntegerField()
    capture_sha256 = models.CharField(max_length=64)
    capture_size = models.PositiveIntegerField()
    generation_report_sha256 = models.CharField(max_length=64)
    generation_report_size = models.PositiveIntegerField()
    initial_validation_job = models.ForeignKey(
        Job, on_delete=models.PROTECT, related_name="initial_corrected_validations"
    )
    created_at = models.DateTimeField(auto_now_add=True)


class DeliveryEvidence(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payload = models.JSONField()
    sha256 = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class DeliveryIntent(DeliveryEvidence):
    job = models.OneToOneField(Job, on_delete=models.PROTECT, related_name="delivery_intent")
    preparation_job = models.ForeignKey(
        Job, on_delete=models.PROTECT, related_name="prepared_deliveries"
    )
    output = models.ForeignKey(CorrectedEpub, on_delete=models.PROTECT, related_name="deliveries")
    source_job = models.ForeignKey(Job, on_delete=models.PROTECT, related_name="delivery_sources")
    validation_job = models.ForeignKey(
        Job, on_delete=models.PROTECT, related_name="delivery_validations"
    )
    assessment_job = models.ForeignKey(
        Job, on_delete=models.PROTECT, null=True, related_name="delivery_assessments"
    )


class DeliveryApproval(DeliveryEvidence):
    intent = models.OneToOneField(DeliveryIntent, on_delete=models.PROTECT, related_name="approval")


class DeliveryTargetBinding(DeliveryEvidence):
    intent = models.OneToOneField(
        DeliveryIntent, on_delete=models.PROTECT, related_name="target_binding"
    )


class DeliveryEvent(DeliveryEvidence):
    intent = models.ForeignKey(DeliveryIntent, on_delete=models.PROTECT, related_name="events")
    job = models.ForeignKey(Job, on_delete=models.PROTECT, related_name="delivery_events")


class DeliveryReceipt(DeliveryEvidence):
    intent = models.ForeignKey(DeliveryIntent, on_delete=models.PROTECT, related_name="receipts")
    job = models.ForeignKey(Job, on_delete=models.PROTECT, related_name="delivery_receipts")
    operation_id = models.UUIDField(unique=True)


class UndoIntent(DeliveryEvidence):
    delivery = models.ForeignKey(DeliveryIntent, on_delete=models.PROTECT, related_name="undos")
    receipt = models.ForeignKey(DeliveryReceipt, on_delete=models.PROTECT, related_name="undos")
    job = models.OneToOneField(Job, on_delete=models.PROTECT, related_name="undo_intent")


class DeliveryState(models.Model):
    intent = models.OneToOneField(
        DeliveryIntent, primary_key=True, on_delete=models.PROTECT, related_name="projection"
    )
    state = models.CharField(max_length=32, default="queued")
    revision = models.PositiveIntegerField(default=1)
    target_key = models.CharField(max_length=64)
    reserved = models.BooleanField(default=True)
    latest_receipt = models.ForeignKey(
        DeliveryReceipt, on_delete=models.PROTECT, null=True, related_name="projections"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["target_key"],
                condition=Q(reserved=True),
                name="one_reserved_delivery_target",
            )
        ]


# Read model of the Calibre library. Calibre remains the source of truth; these rows are
# replaced whole whenever its inventory token changes and are never written back.
class LibraryReadModel(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    root = models.TextField(default="")
    library_uuid = models.TextField(default="")
    # Empty until the first complete import; the token comes from direct_library.state().
    token = models.CharField(max_length=64, default="")
    has_added = models.BooleanField(default=True)
    books = models.PositiveIntegerField(default=0)
    imported_at = models.DateTimeField(null=True)
    observed_at = models.DateTimeField(null=True)
    # Set when Calibre is known to have moved past the imported token.
    stale = models.BooleanField(default=False)
    error = models.TextField(default="", blank=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(id=1), name="one_library_read_model")]


class CalibreAuthor(models.Model):
    calibre_id = models.BigIntegerField(primary_key=True)
    name = models.TextField(null=True)
    # Folded by SQLite's own lower(), so search matches the direct reader exactly.
    name_lower = models.TextField(null=True)


class CalibreSeries(models.Model):
    calibre_id = models.BigIntegerField(primary_key=True)
    name = models.TextField(null=True, db_index=True)


class CalibrePublisher(models.Model):
    calibre_id = models.BigIntegerField(primary_key=True)
    name = models.TextField(null=True)


class CalibreLanguage(models.Model):
    calibre_id = models.BigIntegerField(primary_key=True)
    lang_code = models.TextField(null=True)


class CalibreBook(models.Model):
    calibre_id = models.BigIntegerField(primary_key=True)
    uuid = models.TextField(null=True)
    title = models.TextField(null=True)
    title_lower = models.TextField(null=True)
    sort = models.TextField(null=True)
    path = models.TextField()
    series = models.ForeignKey(CalibreSeries, on_delete=models.PROTECT, null=True)
    series_index = models.FloatField(null=True)
    publisher = models.ForeignKey(CalibrePublisher, on_delete=models.PROTECT, null=True)
    published_at = models.TextField(null=True)
    added_at = models.TextField(null=True)
    cover_media_type = models.TextField(null=True)
    cover_width = models.PositiveIntegerField(null=True)
    cover_height = models.PositiveIntegerField(null=True)
    # dev:inode:size:mtime_ns:ctime_ns of cover.jpg, so an unchanged cover is not reread.
    cover_signature = models.TextField(null=True)


class CalibreBookAuthor(models.Model):
    book = models.ForeignKey(CalibreBook, on_delete=models.CASCADE, related_name="author_links")
    author = models.ForeignKey(CalibreAuthor, on_delete=models.PROTECT)
    position = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["book", "position"], name="one_author_position")
        ]


class CalibreBookLanguage(models.Model):
    book = models.ForeignKey(CalibreBook, on_delete=models.CASCADE, related_name="language_links")
    language = models.ForeignKey(CalibreLanguage, on_delete=models.PROTECT)
    position = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["book", "position"], name="one_language_position")
        ]


class CalibreIdentifier(models.Model):
    book = models.ForeignKey(CalibreBook, on_delete=models.CASCADE, related_name="identifiers")
    position = models.PositiveIntegerField()
    type = models.TextField(null=True)
    value = models.TextField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["book", "position"], name="one_identifier_position")
        ]


class CalibreFormat(models.Model):
    calibre_id = models.BigIntegerField(primary_key=True)
    book = models.ForeignKey(CalibreBook, on_delete=models.CASCADE, related_name="formats")
    position = models.PositiveIntegerField()
    format = models.TextField()
    name = models.TextField()
    recorded_size = models.BigIntegerField(null=True)
    # Observed on the share at import: absent or unreadable files have no size.
    size = models.BigIntegerField(null=True)
    signature = models.TextField(null=True)
    # Empty when hashing this signature failed; null until it is hashed.
    sha256 = models.CharField(max_length=64, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["book", "position"], name="one_format_position")
        ]


class CatalogueStatus(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    source_key = models.CharField(max_length=64, default="")
    payload = models.JSONField(default=dict)
    fetched_at = models.DateTimeField(null=True)
    attempted_at = models.DateTimeField(null=True)
    failure = models.CharField(max_length=100, default="")

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(id=1), name="one_catalogue_status")
        ]


class CoverCensus(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request_key = models.UUIDField(unique=True)
    library_uuid = models.TextField()
    inventory_token = models.CharField(max_length=64)
    detector = models.TextField()
    state = models.CharField(max_length=16, default="pending")
    cursor = models.BigIntegerField(default=0)
    validation_cursor = models.BigIntegerField(default=0)
    total = models.PositiveIntegerField(default=0)
    scanned = models.PositiveIntegerField(default=0)
    remaining = models.PositiveIntegerField(default=0)
    unresolved = models.PositiveIntegerField(default=0)
    error = models.CharField(max_length=64, default="")
    identity_issues = models.JSONField(default=list)
    identity_issue_count = models.PositiveIntegerField(default=0)
    lease_token = models.UUIDField(null=True)
    lease_until = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["library_uuid"],
                condition=Q(state__in=["pending", "running"]),
                name="one_active_cover_census",
            ),
            models.CheckConstraint(
                condition=Q(state__in=["pending", "running", "complete", "partial", "cancelled"]),
                name="cover_census_state",
            ),
            models.CheckConstraint(
                condition=~Q(state="complete") | Q(remaining=0, unresolved=0, error=""),
                name="cover_complete_resolved",
            ),
        ]


class CoverReviewEntry(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    library_uuid = models.TextField()
    book_uuid = models.TextField()
    calibre_id = models.BigIntegerField()
    title = models.TextField(null=True)
    source_signature = models.TextField(default="")
    fingerprint = models.CharField(max_length=64, default="")
    facts = models.JSONField(default=dict)
    present = models.BooleanField(default=True)
    state = models.CharField(max_length=16, default="todo")
    revision = models.PositiveBigIntegerField(default=1)
    skipped_fingerprint = models.CharField(max_length=64, default="")
    changed_since_skipped = models.BooleanField(default=False)
    observed_at = models.DateTimeField(auto_now=True)
    observed_census = models.UUIDField(null=True)
    observed_inventory_signature = models.TextField(default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["library_uuid", "book_uuid"], name="one_cover_book_identity"
            ),
            models.CheckConstraint(
                condition=Q(state__in=["todo", "done", "skipped"]), name="cover_review_state"
            ),
        ]


class CoverReviewAction(models.Model):
    request_key = models.UUIDField(primary_key=True)
    entry = models.ForeignKey(CoverReviewEntry, on_delete=models.PROTECT)
    expected_revision = models.PositiveBigIntegerField()
    skipped = models.BooleanField()
    actor = models.TextField()
    result = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)


class PreparedCover(models.Model):
    """Append-only local choice, without delivery authority or library mutation."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request_key = models.UUIDField(unique=True)
    entry = models.ForeignKey(CoverReviewEntry, on_delete=models.PROTECT)
    actor = models.TextField()
    request = models.JSONField()
    binding = models.JSONField()
    candidate = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["entry", "-created_at", "-id"], name="prepared_cover_latest")
        ]


class CoverSearch(models.Model):
    """Durable nonwriting search; each provider checkpoint is lease-fenced."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request_key = models.UUIDField(unique=True)
    entry = models.ForeignKey(CoverReviewEntry, on_delete=models.PROTECT)
    actor = models.TextField()
    request = models.JSONField()
    binding = models.JSONField()
    query = models.JSONField()
    sources = models.JSONField()
    image_url = models.TextField(default="")
    statuses = models.JSONField(default=dict)
    source_timings = models.JSONField(default=dict)
    candidates = models.JSONField(default=list)
    state = models.CharField(max_length=16, default="queued")
    lease_token = models.UUIDField(null=True)
    lease_until = models.DateTimeField(null=True)
    attempts = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["entry", "created_at", "id"], name="cover_search_entry")]
        constraints = [
            models.CheckConstraint(
                condition=Q(state__in=["queued", "running", "complete", "cancelled", "failed"]),
                name="cover_search_state",
            )
        ]


class SourceBrowserPage(models.Model):
    """Replaceable Goodreads page cache; worker-owned and never browser-mounted."""

    query_key = models.CharField(max_length=64, primary_key=True)
    html = models.TextField()
    url = models.CharField(max_length=4096)
    checked_at = models.DateTimeField()
