"""Bounded presentation of BLC's recorded names, never an identity resolver."""

from librarium.validation import bounded_text

MAX_GROUPS = 64
MAX_ALIASES = 32
MAX_MATCHES = 8


def availability(db) -> str:
    table = db.execute("SELECT type FROM sqlite_schema WHERE name='author_alias'").fetchone()
    if table is None:
        return "missing"
    if table[0] != "table" or not {"author_id", "name"} <= {
        row["name"] for row in db.execute("PRAGMA table_info(author_alias)")
    }:
        return "incompatible"
    db.create_function(
        "group_name_valid",
        1,
        lambda value: isinstance(value, str) and bool(value.strip()) and bounded_text(value, 512),
        deterministic=True,
    )
    # Admission deliberately accepts older snapshots without alias tables. Optional
    # discovery must check this evidence rather than tighten that global contract.
    invalid = db.execute(
        "SELECT 1 FROM author WHERE NOT group_name_valid(name) OR typeof(id)!='integer' OR id<1 "
        "UNION ALL SELECT 1 FROM author_alias aa LEFT JOIN author a ON a.id=aa.author_id "
        "WHERE a.id IS NULL OR typeof(aa.author_id)!='integer' OR NOT group_name_valid(aa.name) "
        "UNION ALL SELECT 1 FROM author GROUP BY id HAVING count(*)>1 "
        "UNION ALL SELECT 1 FROM work_author WHERE role='author' "
        "GROUP BY work_id,author_id HAVING count(*)>1 "
        "UNION ALL SELECT 1 FROM author_alias GROUP BY author_id,name HAVING count(*)>1 LIMIT 1"
    ).fetchone()
    return "invalid" if invalid else "available"


def authors_for(db, work_ids: list[str], selected: int | None, query: str, pattern: str) -> list:
    """Only relevant page authors; one query even for coauthored works."""
    condition = "a.id=?"
    args: list = [selected]
    if work_ids and query:
        condition += (
            " OR (EXISTS (SELECT 1 FROM work_author wa WHERE wa.author_id=a.id "
            f"AND wa.role='author' AND wa.work_id IN ({','.join('?' for _ in work_ids)})) "
            "AND EXISTS (SELECT 1 FROM author_alias aa WHERE aa.author_id=a.id "
            "AND aa.name LIKE ? ESCAPE '\\'))"
        )
        args += [*work_ids, pattern]
    return db.execute(
        f"SELECT id,name FROM author a WHERE {condition} "
        "ORDER BY a.id=? DESC,a.name COLLATE NOCASE,a.id LIMIT 65",
        [*args, selected],
    ).fetchall()


def evidence(db, info: dict, authors: list, state: str, query: str = "", pattern: str = "") -> dict:
    result = {
        "schema_version": "librarium.author-groups.v1",
        "snapshot": info,
        "status": state,
        "groups": [],
        "truncated": False,
    }
    if state != "available":
        return result
    from librarium.package_comparison import name_owners, normalized

    result["truncated"] = len(authors) > MAX_GROUPS
    authors = authors[:MAX_GROUPS]
    if not authors:
        return result
    ids = [row["id"] for row in authors]
    slots = ",".join("?" for _ in ids)
    aliases: dict[str, list] = {str(key): [] for key in ids}
    matches: dict[str, list] = {str(key): [] for key in ids}
    counts = dict.fromkeys(aliases, 0)
    match_counts = dict.fromkeys(aliases, 0)
    # Window counts include every recorded row; caps limit presentation only.
    for row in db.execute(
        "SELECT author_id,name,total FROM (SELECT author_id,name,"
        "count(*) OVER (PARTITION BY author_id) total,"
        "row_number() OVER (PARTITION BY author_id ORDER BY name COLLATE NOCASE,name) rank "
        f"FROM author_alias WHERE author_id IN ({slots})) WHERE rank<=? ORDER BY author_id,rank",
        [*ids, MAX_ALIASES],
    ):
        key = str(row["author_id"])
        aliases[key].append(row["name"])
        counts[key] = row["total"]
    if query:
        for row in db.execute(
            "SELECT author_id,name,total FROM (SELECT author_id,name,"
            "count(*) OVER (PARTITION BY author_id) total,"
            "row_number() OVER (PARTITION BY author_id ORDER BY name COLLATE NOCASE,name) rank "
            f"FROM author_alias WHERE author_id IN ({slots}) AND name LIKE ? ESCAPE '\\') "
            "WHERE rank<=? ORDER BY author_id,rank",
            [*ids, pattern, MAX_MATCHES],
        ):
            key = str(row["author_id"])
            matches[key].append(row["name"])
            match_counts[key] = row["total"]
    # Reuse comparison's complete global collision check once for every shown name,
    # including matched spellings outside the alias display cap.
    owners = name_owners(
        db,
        [row["name"] for row in authors]
        + [name for values in aliases.values() for name in values]
        + [name for values in matches.values() for name in values],
    )

    def spellings(values):
        return [{"name": name, "owners": owners[normalized(name)][1]} for name in values]

    groups = []
    for row in authors:
        key = str(row["id"])
        groups.append(
            {
                "author": {"id": key, "name": row["name"], "version": info["version"]},
                "status": "truncated"
                if counts[key] > MAX_ALIASES or match_counts[key] > MAX_MATCHES
                else "complete",
                "canonical_owners": owners[normalized(row["name"])][1],
                "aliases": spellings(aliases[key]),
                "alias_count": counts[key],
                "matched_aliases": spellings(matches[key]),
                "matched_alias_count": match_counts[key],
            }
        )
    result["groups"] = groups
    return result
