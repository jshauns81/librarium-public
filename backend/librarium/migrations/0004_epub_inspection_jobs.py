from django.db import migrations, models
from django.db.models import Q


def refuse_to_drop_epub_jobs(apps, schema_editor):
    if apps.get_model("librarium", "Job").objects.filter(kind="epub").exists():
        raise RuntimeError(
            "Refusing to reverse 0004 while epub jobs exist; preserve evidence and fix forward."
        )


class Migration(migrations.Migration):
    dependencies = [("librarium", "0003_catalogue_review_jobs")]
    operations = [
        migrations.RemoveConstraint(model_name="job", name="job_kind_matches_target"),
        migrations.AddConstraint(
            model_name="job",
            constraint=models.CheckConstraint(
                condition=Q(kind="synthetic", work__isnull=False)
                | (Q(kind="catalogue", work__isnull=True, fixture_failure=False) & ~Q(target_id=""))
                | Q(
                    kind="epub",
                    work__isnull=True,
                    fixture_failure=False,
                    target_id__regex=r"\A[a-f0-9]{64}\Z",
                ),
                name="job_kind_matches_target",
            ),
        ),
        migrations.AddConstraint(
            model_name="job",
            constraint=models.UniqueConstraint(
                fields=["kind", "target_id"],
                condition=Q(kind="epub", state__in=["queued", "running"]),
                name="one_active_epub_inspection_per_source",
            ),
        ),
        # Reversal must stop before restoring the old kind constraint.
        migrations.RunPython(migrations.RunPython.noop, refuse_to_drop_epub_jobs),
    ]
