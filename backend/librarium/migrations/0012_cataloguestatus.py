from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("librarium", "0011_library_read_model"),
    ]

    operations = [
        migrations.CreateModel(
            name="CatalogueStatus",
            fields=[
                (
                    "id",
                    models.PositiveSmallIntegerField(default=1, primary_key=True, serialize=False),
                ),
                ("source_key", models.CharField(default="", max_length=64)),
                ("payload", models.JSONField(default=dict)),
                ("fetched_at", models.DateTimeField(null=True)),
                ("attempted_at", models.DateTimeField(null=True)),
                ("failure", models.CharField(default="", max_length=100)),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("id", 1)), name="one_catalogue_status"
                    )
                ],
            },
        ),
    ]
