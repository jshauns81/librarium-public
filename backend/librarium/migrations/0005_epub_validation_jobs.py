from django.db import migrations, models
from django.db.models import Q


def refuse_to_drop_validation_jobs(apps, schema_editor):
    if apps.get_model("librarium", "Job").objects.filter(kind="epub_validation").exists():
        raise RuntimeError(
            "Refusing to reverse 0005 while validation jobs exist; preserve evidence and fix forward."
        )


class Migration(migrations.Migration):
    dependencies = [("librarium", "0004_epub_inspection_jobs")]
    operations = [
        migrations.RemoveConstraint(model_name="job", name="job_kind_matches_target"),
        migrations.AddConstraint(
            model_name="job",
            constraint=models.CheckConstraint(
                condition=Q(kind="synthetic", work__isnull=False)
                | (Q(kind="catalogue", work__isnull=True, fixture_failure=False) & ~Q(target_id=""))
                | Q(
                    kind__in=["epub", "epub_validation"],
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
                condition=Q(kind="epub_validation", state__in=["queued", "running"]),
                name="one_active_epub_validation_per_source",
            ),
        ),
        migrations.RunPython(migrations.RunPython.noop, refuse_to_drop_validation_jobs),
    ]
