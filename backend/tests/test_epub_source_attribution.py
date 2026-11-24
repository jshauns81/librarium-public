"""Bounded title/credit observations from synthetic source markup only."""

import hashlib
import json
from copy import deepcopy

import pytest
from librarium.epub_inspection import ENVELOPE_BYTES, InspectionPolicy
from test_epub_inspection import archive, fixture_parts, inspect, page

TITLEPAGE = (
    '<section epub:type="titlepage"><h1 id="one" epub:type="title">'
    'The <em>Printed</em> Book</h1><p epub:type="author">Ada Writer</p></section>'
)


def parts(first=TITLEPAGE, second=None):
    return [
        (
            name,
            page(first)
            if name == "EPUB/first.xhtml"
            else page(second)
            if second is not None and name == "EPUB/second.xhtml"
            else body,
        )
        for name, body in fixture_parts()
    ]


def captured(first=TITLEPAGE, **kwargs):
    result = inspect(archive(parts(first)), **kwargs)
    return result, result["source_attribution"]


@pytest.mark.parametrize("control", ["\x7f", "&#127;"])
@pytest.mark.parametrize("field", ["title", "credit", "heading"])
def test_unsupported_label_text_leaves_a_valid_structural_report(control, field):
    from librarium.source_attribution import validate_source_attribution

    body = (
        TITLEPAGE.replace("The ", f"The{control} ")
        if field == "title"
        else TITLEPAGE.replace("Ada Writer", f"Ada{control} Writer")
        if field == "credit"
        else f'<h1 id="one">Printed{control} title</h1>'
    )
    report, value = captured(body)
    assert report["inspection_complete"] is True
    assert report["structural_check"] == "passed"
    assert value["status"] == "unconfirmed"
    assert value["reason"] == "unsupported_label_text"
    assert value["observations"] == []
    assert validate_source_attribution(report) == value


def test_bad_label_in_second_candidate_cannot_promote_partial_corroboration():
    second = TITLEPAGE.replace('id="one"', 'id="two"').replace("Ada Writer", "Ada&#127; Writer")
    report, value = captured(TITLEPAGE + second)
    assert report["structural_check"] == "passed"
    assert value["status"] == "unconfirmed" and value["observations"] == []


def test_semantic_capture_is_literal_source_bound_and_not_metadata_prompted():
    original = archive(parts())
    digest = hashlib.sha256(original).hexdigest()
    result = inspect(original)
    value = result["source_attribution"]
    assert result["policy"]["version"] == "librarium.epub-structure.v10"
    assert value["policy"] == "librarium.epub-source-attribution.v1"
    assert value["source_sha256"] == digest
    assert value["status"] == "recorded" and value["reason"] is None
    assert value["observations"] == [
        {
            "id": "source-title-1",
            "spine_index": 0,
            "path": "EPUB/first.xhtml",
            "resource_sha256": hashlib.sha256(page(TITLEPAGE)).hexdigest(),
            "source_index": 2,
            "rule": "semantic_titlepage",
            "scope": "container_candidate",
            "title": {"text": "The Printed Book", "source_index": 3, "marker": "title"},
            "credits": [{"text": "Ada Writer", "source_index": 5, "marker": "author"}],
        }
    ]
    assert result["metadata"][1]["text"] == "A synthetic volume"
    assert original == archive(parts()) and hashlib.sha256(original).hexdigest() == digest
    assert result["content_acceptance"] == "not_checked" and result["ready"] is False


def test_wrapper_children_are_captured_before_following_narrative_tail():
    _, value = captured(f"<div>{TITLEPAGE}</div>Narrative follows the title page.")
    assert len(value["observations"]) == 1
    assert value["observations"][0]["title"]["text"] == "The Printed Book"


def test_wrapped_second_candidate_is_not_hidden_by_its_following_tail():
    second = TITLEPAGE.replace('id="one"', 'id="two"')
    _, value = captured(TITLEPAGE + f"<div>{second}</div>Narrative follows both title pages.")
    assert len(value["observations"]) == 2


def test_class_only_frontmatter_is_an_unclassified_lead():
    _, value = captured('<h1 id="one">Printed title</h1><p>Ada Writer</p>')
    assert value["observations"][0]["rule"] == "front_matter_lead"
    assert value["observations"][0]["scope"] == "unclassified"
    assert value["observations"][0]["credits"] == []
    assert "Ada Writer" not in json.dumps(value)


@pytest.mark.parametrize(
    "wrapper",
    [
        "<nav>{}</nav>",
        "<aside>{}</aside>",
        '<section epub:type="toc">{}</section>',
        '<section epub:type="preview">{}</section>',
        '<section epub:type="advertisement">{}</section>',
        '<section hidden="hidden">{}</section>',
        '<section aria-hidden="true">{}</section>',
        '<section style="display: none">{}</section>',
        '<section style="visibility:hidden">{}</section>',
        '<section epub:type="chapter">{}</section>',
    ],
)
def test_excluded_contexts_cannot_capture_the_marked_title(wrapper):
    _, value = captured(wrapper.format(TITLEPAGE))
    assert value["status"] == "unconfirmed" and value["observations"] == []


@pytest.mark.parametrize(
    "prefix",
    [
        '<h1 id="before">Chapter One</h1>',
        "<p>Narrative begins before a later title.</p>",
        '<section epub:type="bodymatter"/>',
    ],
)
def test_story_after_content_in_same_document_cannot_identify_container(prefix):
    _, value = captured(prefix + TITLEPAGE)
    assert value["status"] == "unconfirmed" and value["observations"] == []


def test_later_story_in_next_spine_resource_is_omitted():
    result = inspect(
        archive(
            parts(
                '<h1 id="one">Chapter 1</h1><p>Earlier story.</p>',
                TITLEPAGE.replace('id="one"', 'id="two"'),
            )
        )
    )
    assert result["source_attribution"]["observations"] == []


@pytest.mark.parametrize(
    "replacement",
    [
        "<script>Bad script text</script>",
        '<span hidden="hidden">Hidden</span>',
        '<span style="display:none">Hidden</span>',
    ],
)
def test_hidden_or_script_label_descendants_do_not_enter_eligible_labels(replacement):
    _, value = captured(TITLEPAGE.replace("The <em>Printed</em> Book", replacement))
    assert value["status"] == "unconfirmed" or all(
        item["title"] is None for item in value["observations"]
    )
    assert "Hidden" not in json.dumps(value) and "Bad script" not in json.dumps(value)


def test_image_titlepage_records_no_guessed_title():
    _, value = captured('<section epub:type="titlepage"><img id="one" src="map.svg"/></section>')
    assert value["status"] == "unconfirmed" and value["observations"] == []


def test_duplicate_titlepage_blocks_are_retained_for_ambiguity():
    _, value = captured(TITLEPAGE + TITLEPAGE.replace('id="one"', 'id="again"'))
    assert len(value["observations"]) == 2
    assert [item["id"] for item in value["observations"]] == ["source-title-1", "source-title-2"]


@pytest.mark.parametrize(
    "policy",
    [
        InspectionPolicy(max_records=1),
        InspectionPolicy(max_xml_nodes=1),
        InspectionPolicy(max_output_bytes=ENVELOPE_BYTES),
        InspectionPolicy(max_archive_bytes=1),
    ],
)
def test_inspection_budget_failure_clears_partial_title_observations(policy):
    result, value = captured(policy=policy)
    assert result["structural_check"] == "failed"
    assert value["status"] == "unconfirmed" and value["observations"] == []


def test_label_and_candidate_budgets_do_not_silently_truncate():
    _, value = captured(TITLEPAGE.replace("The <em>Printed</em> Book", "T" * 257))
    assert value["status"] == "unconfirmed" and value["observations"] == []
    _, value = captured("".join(TITLEPAGE.replace('id="one"', f'id="t{n}"') for n in range(9)))
    assert value["status"] == "unconfirmed" and value["observations"] == []


def test_source_structure_failure_clears_otherwise_valid_title_evidence():
    _, value = captured(TITLEPAGE + '<img src="missing.png" alt="Required illustration"/>')
    assert value["status"] == "unconfirmed" and value["observations"] == []


def test_saved_validator_binds_capture_to_document_and_spine_positions():
    from librarium.source_attribution import validate_source_attribution

    report, value = captured()
    assert validate_source_attribution(report) == value
    for key, replacement in [
        ("resource_sha256", "f" * 64),
        ("path", "EPUB/second.xhtml"),
        ("spine_index", 1),
        ("source_index", 999999),
    ]:
        changed = deepcopy(report)
        changed["source_attribution"]["observations"][0][key] = replacement
        with pytest.raises(ValueError):
            validate_source_attribution(changed)
    changed = deepcopy(report)
    changed["source_attribution"]["source_sha256"] = "f" * 64
    with pytest.raises(ValueError):
        validate_source_attribution(changed)


@pytest.mark.parametrize("version", range(1, 7))
def test_historical_reports_retain_absence_instead_of_acquiring_new_capture(version):
    from librarium.source_attribution import validate_source_attribution

    report, _ = captured()
    report["policy"]["version"] = f"librarium.epub-structure.v{version}"
    report.pop("source_attribution")
    assert validate_source_attribution(report) is None
    report["source_attribution"] = {}
    with pytest.raises(ValueError):
        validate_source_attribution(report)


@pytest.mark.parametrize(
    "attribute",
    [
        'hidden="hidden"',
        'aria-hidden="true"',
        'style="display:none"',
        'epub:type="preview"',
    ],
)
def test_excluded_html_ancestor_cannot_supply_body_titlepage(attribute):
    source = page(TITLEPAGE).replace(b"<html ", f"<html {attribute} ".encode(), 1)
    result = inspect(
        archive(
            [
                (name, source if name == "EPUB/first.xhtml" else body)
                for name, body in fixture_parts()
            ]
        )
    )
    assert result["source_attribution"]["observations"] == []


def test_unreadable_container_titlepage_prevents_a_later_story_title_from_becoming_container():
    _, value = captured('<section epub:type="titlepage"><img src="map.svg"/></section>' + TITLEPAGE)
    assert value["status"] == "unconfirmed" and value["observations"] == []


@pytest.mark.parametrize(
    "prefix,expected",
    [
        ("", False),
        ("z3998: http://wrong.invalid/", False),
        ("z3998: http://www.daisy.org/z3998/2012/vocab/structure/#", True),
    ],
)
def test_author_prefix_requires_explicit_supported_vocabulary(prefix, expected):
    markup = TITLEPAGE.replace('epub:type="author"', 'epub:type="z3998:author"')
    source = page(markup).replace(b"<body>", f'<body epub:prefix="{prefix}">'.encode())
    report = inspect(
        archive(
            [
                (name, source if name == "EPUB/first.xhtml" else body)
                for name, body in fixture_parts()
            ]
        )
    )
    assert bool(report["source_attribution"]["observations"][0]["credits"]) is expected


@pytest.mark.parametrize(
    "mutation",
    [
        lambda report: report["source_attribution"]["observations"][0]["title"].update(
            text="T" * 257
        ),
        lambda report: report["source_attribution"]["observations"][0]["credits"][0].update(
            marker="heading"
        ),
        lambda report: report["source_attribution"]["observations"][0].update(scope="contained"),
        lambda report: report["source_attribution"]["observations"][0].update(extra=True),
        lambda report: report["source_attribution"]["observations"][0]["title"].update(
            source_index=True
        ),
        lambda report: report.update(structural_check="failed"),
    ],
)
def test_saved_validator_refuses_forged_shapes_or_ineligible_capture(mutation):
    from librarium.source_attribution import validate_source_attribution

    report, _ = captured()
    mutation(report)
    with pytest.raises(ValueError):
        validate_source_attribution(report)


@pytest.mark.parametrize(
    "prefix",
    ['<span hidden="hidden">Ignored</span>', "<nav>Contents</nav>", "<script>ignored()</script>"],
)
def test_visible_tail_after_excluded_element_stops_later_story_capture(prefix):
    _, value = captured(prefix + "Narrative before a later story." + TITLEPAGE)
    assert value["status"] == "unconfirmed"
    assert value["observations"] == []


@pytest.mark.parametrize(
    "role",
    [
        "doc-chapter",
        "doc-part",
        "doc-prologue",
        "doc-epilogue",
        "doc-toc",
        "doc-index",
        "doc-bibliography",
        "doc-acknowledgments",
        "doc-credits",
        "doc-endnotes",
    ],
)
def test_explicit_document_roles_exclude_contained_or_navigation_titles(role):
    _, value = captured(f'<section role="{role}">{TITLEPAGE}</section>')
    assert value["status"] == "unconfirmed"
    assert value["observations"] == []


def test_correctable_page_link_keeps_recorded_title_evidence():
    report, value = captured(TITLEPAGE + '<a href="missing.xhtml">Broken</a>')
    assert report["structural_check"] == "passed"
    assert value["status"] == "recorded" and value["observations"]
