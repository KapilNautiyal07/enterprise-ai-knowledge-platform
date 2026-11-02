
import json
from pathlib import Path
import re

import requests

import time


API_URL = "http://127.0.0.1:8000/ask/"
DATASET_PATH = Path(__file__).with_name("evaluation_cases.json")

ABSTENTION_PATTERN = re.compile(
    r"(?:"
    r"not enough information\b|"
    r"insufficient evidence\b|"
    r"evidence is insufficient\b|"
    r"i\s+(?:couldn't|could not|cannot|can't)\s+find relevant evidence\b|"
    r"i\s+(?:cannot|can't|could not)\s+determine\b|"
    r"there is no (?:official policy|information|mention)\b|"
    r"no mention of\b|"
    r"not documented\b|"
    r"not covered in the provided evidence\b|"
    r"the provided evidence does not mention\b|"
    r"no documented policy\b"
    r")",
    re.IGNORECASE,
)


def detect_abstention(answer: str) -> bool:
    """Detect a valid abstention or no-evidence answer."""
    return bool(ABSTENTION_PATTERN.search(answer))


def evaluate_case(case: dict) -> dict:
    response = None

    for attempt in range(3):
        try:
            response = requests.post(
                API_URL,
                json={
                    "query": case["query"],
                    "top_k": 5,
                },
                timeout=180,
            )

            if response.status_code < 500:
                response.raise_for_status()
                break

            if attempt < 2:
                print(
                    f"Server error {response.status_code} for "
                    f"{case['id']}; retrying in {2 ** attempt} seconds..."
                )
                time.sleep(2 ** attempt)

        except requests.HTTPError:
            if response is not None and response.status_code in (401, 403, 429):
                raise
            if attempt == 2:
                raise
            print(f"Request failed for {case['id']}; retrying...")
            time.sleep(2 ** attempt)
        except requests.RequestException:
            if attempt == 2:
                raise

            print(f"Request failed for {case['id']}; retrying...")
            time.sleep(2 ** attempt)

    response.raise_for_status()
    result = response.json()


    answer = result.get("answer", "")
    validation = result.get("citation_validation", {})

    keyword_list = case.get("expected_keywords", [])
    keyword_pass = (
        all(word.lower() in answer.lower() for word in keyword_list)
        if keyword_list
        else None
    )

    
    abstained = detect_abstention(answer)
    should_abstain = case.get("should_abstain", False)
    abstention_pass = abstained == should_abstain
    citation_pass = (
        validation.get("valid", False)
        and (
            not should_abstain
            or not validation.get("has_citations", False)
        )
    )

    
    print("Expected abstention:", should_abstain)
    print("Detected abstention:", abstained)

    return {
        "id": case["id"],
        "query": case["query"],
        "keyword_pass": keyword_pass,
        "abstention_pass": abstention_pass,
        "citation_pass": citation_pass,
        "retrieved_chunks": result.get("retrieved_chunks", 0),
        "answer": answer,
    }



def main():
    with DATASET_PATH.open("r", encoding="utf-8") as file:
        cases = json.load(file)

    results = []
    failures = []

    for case in cases:
        try:
            result = evaluate_case(case)
            results.append(result)
            print(f"\n[{result['id']}] {result['query']}")
            print(f"Keyword check: {result['keyword_pass']}")
            print(f"Abstention check: {result['abstention_pass']}")
            print(f"Citation check: {result['citation_pass']}")
            print(f"Retrieved chunks: {result['retrieved_chunks']}")
            print(f"Answer: {result['answer']}")
        except requests.RequestException as exc:
            failures.append({"id": case["id"], "error": str(exc)})
            print(f"\n[{case['id']}] Request failed: {exc}")

    print(f"\nCases evaluated successfully: {len(results)}")
    print(f"Cases failed: {len(failures)}")
    if not results:
        print("\nNo cases were evaluated successfully.")
        return

    print("\n--- Evaluation Summary ---")
    print(
        "Abstention pass rate: "
        f"{sum(r['abstention_pass'] for r in results) / len(results):.0%}"
    )
    print(
        "Citation pass rate: "
        f"{sum(r['citation_pass'] for r in results) / len(results):.0%}"
    )

    keyword_results = [
        r["keyword_pass"]
        for r in results
        if r["keyword_pass"] is not None
    ]

    if keyword_results:
        print(
            "Keyword pass rate: "
            f"{sum(keyword_results) / len(keyword_results):.0%}"
        )

    output_path = DATASET_PATH.with_name("evaluation_results.json")
    output_path.write_text(
        json.dumps(results, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nDetailed results saved to: {output_path}")


if __name__ == "__main__":
    main()
