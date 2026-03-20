#!./.venv/bin/python3

"""
P0.5: Create a fixed 300-item benchmark set stratified by quality bucket.

Output: prepared/benchmark_set.json — 100 high, 100 mid, 100 low.
Ensures at least 50 items come from non-DE sources (EN or other).
"""

import json
import random
import argparse
from collections import defaultdict


def main():
    parser = argparse.ArgumentParser(description="Create stratified benchmark set")
    parser.add_argument("--input", default="prepared/fefe_training_data.json")
    parser.add_argument("--output", default="prepared/benchmark_set.json")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--per-bucket", type=int, default=100)
    parser.add_argument("--min-non-de", type=int, default=50, help="Minimum non-DE source items")
    args = parser.parse_args()

    random.seed(args.seed)

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Deduplicate (weighted sampling may have duplicates)
    seen = set()
    unique = []
    for row in data:
        key = row.get("post_id", id(row))
        if key not in seen:
            seen.add(key)
            unique.append(row)

    # Split by bucket
    by_bucket = defaultdict(list)
    for row in unique:
        by_bucket[row.get("quality_bucket", "mid")].append(row)

    # Identify non-DE items (context starts with [Quelle: XX] where XX != DE)
    def is_non_de(row):
        ctx = row.get("context", "")
        return ctx.startswith("[Quelle:") and not ctx.startswith("[Quelle: DE]")

    benchmark = []
    non_de_count = 0

    for bucket in ["high", "mid", "low"]:
        pool = by_bucket[bucket]
        random.shuffle(pool)

        # Prioritize non-DE items to meet the minimum
        non_de_items = [r for r in pool if is_non_de(r)]
        de_items = [r for r in pool if not is_non_de(r)]

        selected = []
        # If we still need non-DE items, pull from this bucket
        non_de_needed = max(0, (args.min_non_de - non_de_count))
        non_de_take = min(len(non_de_items), non_de_needed, args.per_bucket // 2)
        selected.extend(non_de_items[:non_de_take])
        non_de_count += non_de_take

        # Fill remaining from DE items
        remaining = args.per_bucket - len(selected)
        selected.extend(de_items[:remaining])

        # If still not enough, take more non-DE
        if len(selected) < args.per_bucket:
            extra = non_de_items[non_de_take:non_de_take + (args.per_bucket - len(selected))]
            selected.extend(extra)
            non_de_count += len(extra)

        benchmark.extend(selected[:args.per_bucket])

    # Add rubric fields for manual scoring
    for item in benchmark:
        item["rubric_style_fidelity"] = None  # 0-3
        item["rubric_topical_relevance"] = None  # 0-3
        item["rubric_hallucination_risk"] = None  # 0-3
        item["rubric_notes"] = ""

    random.shuffle(benchmark)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(benchmark, f, ensure_ascii=False, indent=2)

    # Report
    bucket_counts = defaultdict(int)
    for item in benchmark:
        bucket_counts[item.get("quality_bucket", "?")] += 1

    actual_non_de = sum(1 for item in benchmark if is_non_de(item))

    print("Benchmark set: {} items".format(len(benchmark)))
    for b in ["high", "mid", "low"]:
        print("  {}: {}".format(b, bucket_counts[b]))
    print("  non-DE items: {}".format(actual_non_de))
    print("Saved to {}".format(args.output))


if __name__ == "__main__":
    main()
