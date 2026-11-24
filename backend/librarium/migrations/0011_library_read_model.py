"""A replaceable read model of the Calibre library; reversing it loses nothing Calibre lacks."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("librarium", "0010_evidence_guards"),
    ]

    operations = [
        migrations.CreateModel(
            name="CalibreAuthor",
            fields=[
                ("calibre_id", models.BigIntegerField(primary_key=True, serialize=False)),
                ("name", models.TextField(null=True)),
                ("name_lower", models.TextField(null=True)),
            ],
        ),
        migrations.CreateModel(
            name="CalibreLanguage",
            fields=[
                ("calibre_id", models.BigIntegerField(primary_key=True, serialize=False)),
                ("lang_code", models.TextField(null=True)),
            ],
        ),
        migrations.CreateModel(
            name="CalibrePublisher",
            fields=[
                ("calibre_id", models.BigIntegerField(primary_key=True, serialize=False)),
                ("name", models.TextField(null=True)),
            ],
        ),
        migrations.CreateModel(
            name="CalibreSeries",
            fields=[
                ("calibre_id", models.BigIntegerField(primary_key=True, serialize=False)),
                ("name", models.TextField(db_index=True, null=True)),
            ],
        ),
        migrations.CreateModel(
            name="CalibreBook",
            fields=[
                ("calibre_id", models.BigIntegerField(primary_key=True, serialize=False)),
                ("uuid", models.TextField(null=True)),
                ("title", models.TextField(null=True)),
                ("title_lower", models.TextField(null=True)),
                ("sort", models.TextField(null=True)),
                ("path", models.TextField()),
                ("series_index", models.FloatField(null=True)),
                ("published_at", models.TextField(null=True)),
                ("added_at", models.TextField(null=True)),
                ("cover_media_type", models.TextField(null=True)),
                ("cover_width", models.PositiveIntegerField(null=True)),
                ("cover_height", models.PositiveIntegerField(null=True)),
                ("cover_signature", models.TextField(null=True)),
                (
                    "publisher",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        to="librarium.calibrepublisher",
                    ),
                ),
                (
                    "series",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        to="librarium.calibreseries",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="LibraryReadModel",
            fields=[
                (
                    "id",
                    models.PositiveSmallIntegerField(default=1, primary_key=True, serialize=False),
                ),
                ("root", models.TextField(default="")),
                ("library_uuid", models.TextField(default="")),
                ("token", models.CharField(default="", max_length=64)),
                ("has_added", models.BooleanField(default=True)),
                ("books", models.PositiveIntegerField(default=0)),
                ("imported_at", models.DateTimeField(null=True)),
                ("observed_at", models.DateTimeField(null=True)),
                ("stale", models.BooleanField(default=False)),
                ("error", models.TextField(blank=True, default="")),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("id", 1)), name="one_library_read_model"
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="CalibreBookAuthor",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("position", models.PositiveIntegerField()),
                (
                    "author",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="librarium.calibreauthor"
                    ),
                ),
                (
                    "book",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="author_links",
                        to="librarium.calibrebook",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(fields=("book", "position"), name="one_author_position")
                ],
            },
        ),
        migrations.CreateModel(
            name="CalibreFormat",
            fields=[
                ("calibre_id", models.BigIntegerField(primary_key=True, serialize=False)),
                ("position", models.PositiveIntegerField()),
                ("format", models.TextField()),
                ("name", models.TextField()),
                ("recorded_size", models.BigIntegerField(null=True)),
                ("size", models.BigIntegerField(null=True)),
                ("signature", models.TextField(null=True)),
                ("sha256", models.CharField(max_length=64, null=True)),
                (
                    "book",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="formats",
                        to="librarium.calibrebook",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(fields=("book", "position"), name="one_format_position")
                ],
            },
        ),
        migrations.CreateModel(
            name="CalibreIdentifier",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("position", models.PositiveIntegerField()),
                ("type", models.TextField(null=True)),
                ("value", models.TextField(null=True)),
                (
                    "book",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="identifiers",
                        to="librarium.calibrebook",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("book", "position"), name="one_identifier_position"
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="CalibreBookLanguage",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("position", models.PositiveIntegerField()),
                (
                    "book",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="language_links",
                        to="librarium.calibrebook",
                    ),
                ),
                (
                    "language",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="librarium.calibrelanguage"
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("book", "position"), name="one_language_position"
                    )
                ],
            },
        ),
    ]
