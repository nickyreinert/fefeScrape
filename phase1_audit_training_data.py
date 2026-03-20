#!./.venv/bin/python3

"""
Audit the prepared training data — reports quality buckets,
topic sources, suspicious patterns, and example rows per bucket.
"""

import json
import re
from collections import Counter, defaultdict

from prompt_template import normalize_whitespace

DATASET_PATH = "prepared/fefe_training_data.json"
MAX_EXAMPLES_PER_BUCKET = 5

SUSPICIOUS_PATTERNS = [
    ("javascript-placeholder", re.compile(r"javascript is not available", re.IGNORECASE)),
    ("wikipedia-title", re.compile(r"wikipedia", re.IGNORECASE)),
    ("maps-link", re.compile(r"google\.[^\s]+/maps|\bmaps?\b", re.IGNORECASE)),
    ("postal-code-lead", re.compile(r"^\d{5}\b")),
    ("very-short-topic", re.compile(r"^.{0,18}$")),
    ("quoted-fragment", re.compile(r'^["\'].+["\']$')),
    ("generic-page-title", re.compile(r"^(home|startseite|index|news|artikel)$", re.IGNORECASE)),
    ("url-ish", re.compile(r"(https?://|www\.|utm_)", re.IGNORECASE)),
]


def classify_topic(topic):
    normalized = normalize_whitespace(topic)
    if not normalized:
        return "empty"
    for label, pattern in SUSPICIOUS_PATTERNS:
        if pattern.search(normalized):
            return label
    lowered = normalized.lower()
    if lowered.count("|") >= 2:
        return "metadata-heavy"
    if sum(char.isdigit() for char in normalized) >= 6:
        return "digit-heavy"
    return "ok"


def main():
    with open(DATASET_PATH, "r", encoding="utf-8") as handle:
        dataset = json.load(handle)

    bucket_counts = Counter()
    bucket_examples = defaultdict(list)
    quality_buckets = Counter()
    source_counts = Counter()
    top_topics = Counter()

    for row in dataset:
        topic = normalize_whitespace(row.get("topic", ""))
        bucket = classify_topic(topic)
        bucket_counts[bucket] += 1
        top_topics[topic] += 1

        # New fields
        quality_buckets[row.get("quality_bucket", "unknown")] += 1
        source_counts[row.get("topic_source", "unknown")] += 1

        if len(bucket_examples[bucket]) < MAX_EXAMPLES_PER_BUCKET:
            bucket_examples[bucket].append({
                "topic": topic,
                "context": normalize_whitespace(row.get("context", "")),
                "url": normalize_whitespace(row.get("url", "")),
                "post_url": normalize_whitespace(row.get("post_url", "")),
                "quality_score": row.get("quality_score", "?"),
                "quality_bucket": row.get("quality_bucket", "?"),
                "topic_source": row.get("topic_source", "?"),
            })

    total_rows = len(dataset)
    suspicious_total = total_rows - bucket_counts["ok"]

    print("=== Dataset Overview ===")
    print("Total rows: {}".format(total_rows))
    print("Suspicious topic rows: {}".format(suspicious_total))

    print("\n=== Quality Buckets (from scoring) ===")
    for bucket, count in quality_buckets.most_common():
        pct = 100.0 * count / total_rows if total_rows else 0
        print("  {}: {} ({:.1f}%)".format(bucket, count, pct))

    print("\n=== Topic Sources ===")
    for source, count in source_counts.most_common():
        pct = 100.0 * count / total_rows if total_rows else 0
        print("  {}: {} ({:.1f}%)".format(source, count, pct))

    print("\n=== Suspicious Pattern Buckets ===")
    for label, count in bucket_counts.most_common():
        print("  {}: {}".format(label, count))

    print("\n=== Examples by Suspicious Bucket ===")
    for label, count in bucket_counts.most_common():
        if label == "ok":
            continue
        print("\n[{}] {}".format(label, count))
        for ex in bucket_examples[label]:
            print("  topic: {}".format(ex["topic"]))
            if ex["context"]:
                print("  context: {}".format(ex["context"]))
            print("  source={} score={} bucket={}".format(
                ex["topic_source"], ex["quality_score"], ex["quality_bucket"]))
            print()

    print("=== Most Frequent Topics ===")
    for topic, count in top_topics.most_common(15):
        print("  {} ({})".format(topic, count))


if __name__ == "__main__":
    main()
