
import re


CITATION_PATTERN = re.compile(
    r"\[((?:S\d+)(?:\s*,\s*S\d+)*)\]"
)


def extract_citations(answer: str) -> set[str]:
    cited_ids = set()

    for match in CITATION_PATTERN.findall(answer):
        cited_ids.update(
            label.strip()
            for label in match.split(",")
        )

    return cited_ids



def validate_citations(
    answer: str,
    sources: list[dict],
) -> dict:
    """
    Validate citation labels against the sources
    provided to the LLM.

    This checks citation references, not whether
    a source semantically supports a claim.
    """

    valid_source_ids = {
        source["source_id"]
        for source in sources
        if source.get("source_id")
    }

    cited_ids = extract_citations(answer)

    valid_citations = sorted(cited_ids & valid_source_ids)
    invalid_citations = sorted(cited_ids - valid_source_ids)

    return {
        "valid": len(invalid_citations) == 0,
        "citations_found": sorted(cited_ids),
        "valid_citations": valid_citations,
        "invalid_citations": invalid_citations,
        "has_citations": len(cited_ids) > 0,
        "citation_coverage": (
            round(len(valid_citations) / len(cited_ids), 2)
            if cited_ids
            else 0.0
        ),
    }
