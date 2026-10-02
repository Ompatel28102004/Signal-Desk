from backend.app.ingestion.models import RawMention, normalize_mention
from backend.app.ingestion.processing import MentionProcessingPipeline


def _mention(
    source: str,
    external_id: str,
    *,
    title: str | None,
    content: str | None,
    url: str | None = None,
):
    return normalize_mention(
        source,
        "spring launch",
        RawMention(
            external_id=external_id,
            title=title,
            content=content,
            url=url,
        ),
    )


def test_html_cleanup_whitespace_url_normalization_and_relevance() -> None:
    mention = _mention(
        "news",
        "release-1",
        title="<h1>Spring &amp; Launch</h1>",
        content="<p>  Product&nbsp;details </p><script>ignore this</script><style>hidden</style>",
        url="HTTPS://Example.COM:443/news/item?utm_source=digest&campaign=spring#top",
    )

    result = MentionProcessingPipeline().process([mention], "spring launch")

    assert len(result.mentions) == 1
    cleaned = result.mentions[0]
    assert cleaned.title == "Spring & Launch"
    assert cleaned.content == "Product details"
    assert cleaned.url == "https://example.com/news/item?campaign=spring"
    assert cleaned.normalized_text == "spring & launch\nproduct details"
    assert cleaned.content_hash
    assert cleaned.relevance_score == 0.8
    assert cleaned.relevance_reason == "all_keyword_terms_present"


def test_same_source_and_external_id_is_rejected_as_exact_duplicate() -> None:
    first = _mention(
        "rss:one",
        "story-1",
        title="Spring launch",
        content="The new product is here.",
    )
    duplicate = _mention(
        "rss:one",
        "story-1",
        title="Spring launch updated",
        content="A newer copy of the same item.",
    )

    result = MentionProcessingPipeline().process([first, duplicate], "spring launch")

    assert [item.external_id for item in result.mentions] == ["story-1"]
    assert [item.reason for item in result.rejections] == ["duplicate_source_external_id"]


def test_same_article_from_different_feeds_is_rejected_by_content_hash() -> None:
    first = _mention(
        "rss:one",
        "story-a",
        title="Spring launch",
        content="The new product is here.",
    )
    syndicated = _mention(
        "rss:two",
        "story-b",
        title=" SPRING   LAUNCH ",
        content="The NEW product is here.",
    )

    result = MentionProcessingPipeline().process([first, syndicated], "spring launch")

    assert [item.source for item in result.mentions] == ["rss:one"]
    assert [item.reason for item in result.rejections] == ["duplicate_content_hash"]
    assert first.content_hash == syndicated.content_hash


def test_incidental_keyword_substring_and_url_do_not_make_relevant_content() -> None:
    mention = normalize_mention(
        "news",
        "art",
        RawMention(
            external_id="incidental",
            title="Party plans announced",
            content="This report discusses music and fine arts.",
            url="https://example.com/story?keyword=art",
        ),
    )

    result = MentionProcessingPipeline().process([mention], "art")

    assert result.mentions == []
    assert [item.reason for item in result.rejections] == ["keyword_not_in_content"]


def test_empty_html_content_is_filtered() -> None:
    mention = _mention(
        "news",
        "empty",
        title="<p>   </p><script>spring launch</script>",
        content="<div><br></div><style>.spring { display: none }</style>",
    )

    result = MentionProcessingPipeline().process([mention], "spring launch")

    assert result.mentions == []
    assert [item.reason for item in result.rejections] == ["empty_content"]


def test_all_keyword_terms_across_title_and_content_are_accepted() -> None:
    mention = _mention(
        "news",
        "distributed-match",
        title="Spring arrives",
        content="A launch for the new season.",
    )

    result = MentionProcessingPipeline().process([mention], "spring launch")

    assert len(result.mentions) == 1
    assert result.mentions[0].relevance_score == 0.8
    assert result.mentions[0].relevance_reason == "all_keyword_terms_present"