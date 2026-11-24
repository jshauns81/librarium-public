"""Choice grouping is a pure function of the whole record set, never of processing order."""

import hashlib
import itertools

import pytest
from librarium import cover_sources as sources

HOST = "https://is1-ssl.mzstatic.com/image/thumb"


def rec(name, sha, asset, size=1600, ext="jpg", rank=0):
    item = {
        "id": name,
        "sha256": hashlib.sha256(sha.encode()).hexdigest(),
        "source_url": f"{HOST}/{asset}/{size}x{size}bb.{ext}",
        "method": "web_original",
        "width": 600,
        "height": 900,
        "media_type": "image/jpeg",
        "selectable": True,
    }
    return {"item": item, "url": f"/images/{name}", "rank": rank}


def legacy(name, url, rank):
    item = {"id": name, "source_url": url, "method": "web_original"}
    return {"item": item, "url": f"/images/{name}", "rank": rank}


def shown(records, saved=None, saved_url="/images/saved", limit=24):
    return [c["id"] for c in sources.choose_images(records, saved, saved_url, limit)]


def every_order(records, **kw):
    results = {tuple(shown(list(order), **kw)) for order in itertools.permutations(records)}
    assert len(results) == 1, results
    return list(results.pop())


def test_bridge_by_old_record_keeps_both_current_images_in_every_order():
    records = [
        rec("b", "y", "asset-b", rank=3),
        rec("old", "x", "asset-b", rank=2),
        rec("a", "x", "asset-a", rank=1),
    ]
    assert every_order(records) == ["b", "old"]


def test_renditions_of_one_artwork_merge_to_the_newest_in_every_order():
    records = [rec("new", "y", "asset-a", 1600, rank=2), rec("old", "x", "asset-a", 3000, rank=1)]
    assert every_order(records) == ["new"]


def test_renditions_in_different_formats_merge():
    records = [rec("w", "x", "asset-a", 3000, "webp", 1), rec("j", "y", "asset-a", 1600, "jpg", 2)]
    assert every_order(records) == ["j"]


def test_same_size_in_two_formats_is_one_artwork_in_two_encodings():
    records = [
        rec("j16", "a", "asset-a", 1600, "jpg", rank=3),
        rec("w16", "b", "asset-a", 1600, "webp", rank=2),
        rec("j30", "c", "asset-a", 3000, "jpg", rank=1),
    ]
    assert every_order(records) == ["j16"]


def test_same_size_and_same_format_with_different_bytes_merges_nothing_on_that_path():
    records = [
        rec("one", "a", "asset-a", 1600, "jpg", rank=2),
        rec("two", "b", "asset-a", 1600, "jpg", rank=1),
    ]
    assert every_order(records) == ["one", "two"]


def test_artwork_replaced_at_one_path_keeps_both_images():
    records = [rec("cur", "y", "asset-b", rank=2), rec("old", "x", "asset-b", rank=1)]
    assert every_order(records) == ["cur", "old"]


def test_three_images_on_a_path_with_a_replaced_pair_merge_nothing():
    records = [
        rec("x", "x", "asset-a", 1600, rank=3),
        rec("y", "y", "asset-a", 1600, rank=2),
        rec("z", "z", "asset-a", 3000, rank=1),
    ]
    assert every_order(records) == ["x", "y", "z"]


def test_different_artwork_paths_never_merge():
    records = [rec("a", "x", "asset-a", rank=2), rec("b", "y", "asset-b", rank=1)]
    assert every_order(records) == ["a", "b"]


def test_a_byte_group_on_two_paths_never_path_merges_a_third_image():
    records = [
        rec("a1", "x", "asset-a", 1600, rank=4),
        rec("b1", "x", "asset-b", 1600, rank=3),
        rec("a2", "y", "asset-a", 3000, rank=2),
        rec("b2", "z", "asset-b", 3000, rank=1),
    ]
    assert every_order(records) == ["a1", "a2", "b2"]


def test_saved_exact_record_represents_its_group_even_with_a_same_bytes_sibling():
    records = [rec("s1", "x", "asset-a", rank=2), rec("s2", "x", "asset-a", rank=1)]
    saved = rec("s2", "x", "asset-a")["item"]
    assert every_order(records, saved=saved) == ["s2"]
    assert every_order(records) == ["s1"]


def test_saved_record_outside_the_history_is_added_and_represents_its_bytes():
    records = [rec("s1", "x", "asset-a", rank=2)]
    saved = rec("gone", "x", "asset-a")["item"]
    assert every_order(records, saved=saved) == ["gone"]


def test_saved_rendition_represents_the_merged_artwork():
    records = [rec("new", "y", "asset-a", 1600, rank=2)]
    saved = rec("old", "x", "asset-a", 3000)["item"]
    assert every_order(records, saved=saved) == ["old"]


def test_saved_selection_beside_a_replaced_image_adds_a_choice_not_a_merge():
    records = [rec("cur", "y", "asset-b", 3000, rank=2)]
    saved = rec("p", "p", "asset-b", 3000)["item"]
    assert every_order(records, saved=saved) == ["cur", "p"]


@pytest.mark.parametrize("saved_in_history", [True, False])
def test_cap_never_evicts_the_saved_choice_or_an_unrelated_one_it_belongs_beside(saved_in_history):
    records = [rec(f"r{n}", f"{n:x}", f"asset-{n}", rank=100 - n) for n in range(24)]
    saved = rec("gone", "0", "asset-0")["item"]
    out = shown(records, saved=saved)
    assert len(out) == 24 and "gone" in out and "r0" not in out
    assert {f"r{n}" for n in range(1, 24)} <= set(out)
    if saved_in_history:
        records.append(rec("gone", "0", "asset-0", rank=0))
        assert shown(records, saved=saved) == out


def test_cap_evicts_the_oldest_other_choice_for_a_saved_choice_that_needs_a_group():
    records = [rec(f"r{n}", f"{n:x}", f"asset-{n}", rank=100 - n) for n in range(24)]
    saved = rec("p", "new-image", "asset-p")["item"]
    out = shown(records, saved=saved)
    assert len(out) == 24 and "p" in out and "r23" not in out


def test_legacy_records_without_a_digest_fall_back_to_their_normalised_url():
    records = [
        legacy("n", "https://EXAMPLE.org:443/art", 3),
        legacy("o", "https://example.org/art", 2),
        legacy("d", "https://example.org/other", 1),
    ]
    assert every_order(records) == ["n", "d"]


def test_no_distinct_image_is_missing_across_random_adversarial_sets():
    import random

    rng = random.Random(11)
    for _ in range(300):
        records = [
            rec(
                f"r{n}",
                rng.choice("xyz"),
                rng.choice(["asset-a", "asset-b"]),
                rng.choice([1600, 3000]),
                rng.choice(["jpg", "webp"]),
                rank=10 - n,
            )
            for n in range(rng.randint(1, 5))
        ]
        expected = shown(records)
        for order in itertools.islice(itertools.permutations(records), 24):
            assert shown(list(order)) == expected
        out = sources.choose_images(records, None, "", 24)
        assert len({c["id"] for c in out}) == len(out)
        assert out
