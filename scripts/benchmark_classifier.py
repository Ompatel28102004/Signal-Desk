import argparse
import time

from backend.app.ingestion.models import RawMention, normalize_mention
from backend.app.nlp.classifier import DeterministicMentionClassifier


SAMPLE_TEXTS = (
    (
        "New product launch",
        "I love the new features and the build quality is excellent. Setup was easy.",
    ),
    (
        "Pricing update",
        "The subscription price is expensive and customer support was slow to respond.",
    ),
    (
        "A neutral product overview",
        "The package arrived Tuesday and includes three components in the standard box.",
    ),
    (
        "Compared with competitors",
        "This alternative is reliable but its price is high compared with competitors.",
    ),
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark deterministic mention classification")
    parser.add_argument("--count", type=int, default=10_000)
    count = parser.parse_args().count
    if count < 1:
        parser.error("--count must be positive")

    mentions = [
        normalize_mention(
            "benchmark",
            "product",
            RawMention(
                external_id=str(index),
                title=SAMPLE_TEXTS[index % len(SAMPLE_TEXTS)][0],
                content=SAMPLE_TEXTS[index % len(SAMPLE_TEXTS)][1],
            ),
        )
        for index in range(count)
    ]
    classifier = DeterministicMentionClassifier()
    started = time.perf_counter()
    classified = classifier.classify_many(mentions)
    elapsed = time.perf_counter() - started
    print(
        f"records={len(classified)} seconds={elapsed:.4f} "
        f"records_per_second={len(classified) / elapsed:.0f}"
    )


if __name__ == "__main__":
    main()