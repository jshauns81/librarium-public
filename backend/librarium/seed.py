import hashlib

from django.db import transaction

from librarium.models import Work

TITLES = [
    "The Glass Meridian",
    "A Map of Quiet Stars",
    "The Last Orchard",
    "Letters from the Tidelands",
    "The Cartographer's Winter",
    "An Atlas of Small Wonders",
    "The House Beyond the Reeds",
    "A Field Guide to Returning",
    "The Night Archive",
    "Where the River Remembers",
    "The Blue Hour",
    "The Long Way Inland",
]
AUTHORS = ["Mara Ellison", "Soren Vale", "Iona Mercer", "Ada Rowan", "Elias Finch", "Nell Arden"]


@transaction.atomic
def seed(count: int = 5522) -> None:
    if not 1 <= count <= 10000:
        raise ValueError("Fixture size must be 1 to 10000")
    works = []
    for index in range(count):
        number = index + 1
        title = TITLES[index % len(TITLES)] + (
            f" · Volume {index // len(TITLES) + 1}" if index >= len(TITLES) else ""
        )
        work_id = f"demo-{number:05}"
        author = AUTHORS[index % len(AUTHORS)]
        series = ["The Meridian Papers", "The Northern Archive", "Tideland Stories"][index % 3]
        editions = [
            {
                "id": f"synthetic-edition-{number}-digital",
                "format": "EPUB",
                "isbn": "9780306406157",
                "year": 2024,
            }
        ]
        if index % 2 == 0:
            editions.append(
                {
                    "id": f"synthetic-edition-{number}-print",
                    "format": "Paperback",
                    "isbn": None,
                    "year": 2023,
                }
            )
        payload = {
            "id": work_id,
            "synthetic": True,
            "title": title,
            "author": author,
            "series": series,
            "source_version": "synthetic-catalogue-v1",
            "library_uuid": f"synthetic-library-{number}",
            "file_sha256": hashlib.sha256(f"synthetic-file-{number}".encode()).hexdigest(),
            "library_title": "A Different Map" if number == 2 else title,
            "library_isbn": "9780306406158" if number == 2 else "9780306406157",
            "fault": "once" if number == 3 else None,
            "editions": editions,
            "evidence": [
                {
                    "source": "synthetic-catalogue",
                    "field": "title",
                    "value": title,
                    "native_id": f"fixture-{number}",
                    "observed_at": "2026-10-24",
                }
            ],
            "description": "A fictional entry for exercising collection browsing and metadata comparison. Its identifiers and evidence are test fixtures.",
        }
        works.append(Work(id=work_id, title=title, author=author, series=series, payload=payload))
    Work.objects.bulk_create(works, ignore_conflicts=True)
