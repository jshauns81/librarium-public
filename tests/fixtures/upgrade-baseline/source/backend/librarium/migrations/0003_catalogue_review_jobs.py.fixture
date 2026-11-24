import django.db.models.deletion
from django.db import migrations, models
from django.db.models import F, Q


def backfill_targets(apps, schema_editor):
    apps.get_model("librarium", "Job").objects.filter(target_id="").update(target_id=F("work_id"))


def refuse_to_drop_reviews(apps, schema_editor):
    Job = apps.get_model("librarium", "Job")
    count = Job.objects.filter(Q(kind="catalogue") | Q(work__isnull=True)).count()
    if count:
        raise RuntimeError(
            f"Refusing to reverse 0003: {count} catalogue review job(s) have no synthetic Work. "
            "Export or remove them deliberately before reversing this migration."
        )


class Migration(migrations.Migration):
    dependencies = [
        ("librarium", "0002_isolate_fixture_control"),
    ]

    operations = [
        migrations.AddField(
            model_name="job",
            name="kind",
            field=models.CharField(default="synthetic", max_length=20),
        ),
        migrations.AddField(
            model_name="job",
            name="target_id",
            field=models.CharField(blank=True, default="", max_length=80),
        ),
        migrations.RunPython(backfill_targets, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="job",
            name="work",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                to="librarium.work",
            ),
        ),
        migrations.AddIndex(
            model_name="job",
            index=models.Index(fields=["kind", "target_id"], name="job_kind_target_idx"),
        ),
        migrations.AddConstraint(
            model_name="job",
            constraint=models.UniqueConstraint(
                condition=Q(kind="catalogue", state__in=["queued", "running"]),
                fields=("kind", "target_id"),
                name="one_active_catalogue_review_per_target",
            ),
        ),
        migrations.AddConstraint(
            model_name="job",
            constraint=models.CheckConstraint(
                condition=Q(kind="synthetic", work__isnull=False)
                | (
                    Q(kind="catalogue", work__isnull=True, fixture_failure=False) & ~Q(target_id="")
                ),
                name="job_kind_matches_target",
            ),
        ),
        # Runs first when reversing: restoring NOT NULL on work would otherwise fail midway,
        # and dropping review rows to make it pass would silently lose durable records.
        migrations.RunPython(migrations.RunPython.noop, refuse_to_drop_reviews),
    ]
