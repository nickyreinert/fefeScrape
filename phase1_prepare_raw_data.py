#!./.venv/bin/python3

"""
Phase 1: Prepare training data from raw Fefe blog posts.

Implements HTML-first topic extraction (P0.1/P0.2), hard-drop filters (P0.3),
quality scoring with weighted sampling (P0.4), and language detection (P1.3).
"""

import argparse
import json
import math
import random
import re
from pathlib import Path

from bs4 import BeautifulSoup
from langdetect import detect, LangDetectException

from prompt_template import normalize_whitespace

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIN_COMMENT_LENGTH = 30

DEICTIC = re.compile(r"\b(das hier|dies|hier|was das|was das hier)\b", re.I)
MAPS_URL = re.compile(r"google\.(de|com)/maps", re.I)
MAPS_BOILER = re.compile(
    r"(find local businesses|view maps|driving directions|google maps"
    r"|postleitzahl\s*\|\s*quelle)",
    re.I,
)

# Hard-drop patterns (P0.3)
URL_ISH = re.compile(r"(https?://|www\.|utm_|\.\w{2,3}/|\?)", re.I)
GENERIC_PORTAL = re.compile(
    r"(startseite|home\s*[-|]|index\s*[-|]|navigation|"
    r"javascript is not available|"
    r"reddit\s*-\s*the heart|cookie\s*(policy|settings|hinweis))",
    re.I,
)
SEPARATOR_SOUP = re.compile(r"[|•–—/\\]{2,}")
BRAND_DOMAINS = re.compile(
    r"^(spiegel\.de|zeit\.de|tagesschau\.de|sueddeutsche\.de|"
    r"derstandard\.at|heise\.de|golem\.de|faz\.net|bild\.de|"
    r"theguardian\.com|nytimes\.com|washingtonpost\.com|bbc\.co\.uk|"
    r"reuters\.com|twitter\.com|youtube\.com|github\.com)$",
    re.I,
)

# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------


def is_external_link(a):
    href = (a.get("href") or "").strip()
    if not href:
        return False
    if href.startswith("?ts="):
        return False
    return href.startswith("http://") or href.startswith("https://")


def first_external_anchors(soup):
    out = []
    for a in soup.find_all("a"):
        if is_external_link(a):
            out.append((a.get("href"), normalize_whitespace(a.get_text(" ", strip=True)), a))
    return out


def nearest_blockquote_after(a_tag, max_chars=140):
    node = a_tag
    for _ in range(20):
        node = getattr(node, "next_element", None)
        if node is None:
            break
        if getattr(node, "name", None) == "blockquote":
            return normalize_whitespace(node.get_text(" ", strip=True))[:max_chars]
    return ""


def next_sentence_after(a_tag, max_chars=140):
    node = a_tag
    buf = []
    for _ in range(60):
        node = getattr(node, "next_element", None)
        if node is None:
            break
        if isinstance(node, str):
            t = normalize_whitespace(node)
            if t:
                buf.append(t)
                joined = " ".join(buf)
                if joined.endswith((".", "!", "?")) or len(joined) >= max_chars:
                    return joined[:max_chars]
    return " ".join(buf)[:max_chars]


# ---------------------------------------------------------------------------
# Core extraction (P0.1, P0.2, P1.2)
# ---------------------------------------------------------------------------


def build_topic_context_from_html(content_html, external_title="", external_desc=""):
    soup = BeautifulSoup(content_html, "html.parser")
    anchors = first_external_anchors(soup)

    topic = ""
    context = ""
    source = "none"

    if anchors:
        url1, text1, a1 = anchors[0]
        topic = text1
        source = "html_anchor"

        bq = nearest_blockquote_after(a1)
        if bq and 20 <= len(bq) <= 140:
            topic = "{}: {}".format(topic, bq)
            source = "html_anchor+blockquote"

        # Deictic resolution (P1.2)
        if DEICTIC.search(text1):
            extra = next_sentence_after(a1)
            if extra and len(extra) >= 20:
                topic = "{} {}".format(text1, extra)
                source = "html_text"
            elif len(anchors) > 1 and len(anchors[1][1]) >= 20:
                topic = "{} ({})".format(text1, anchors[1][1])
                source = "html_text"

        # Maps special-case (P1.2)
        if MAPS_URL.search(url1 or ""):
            if MAPS_BOILER.search(topic) or len(topic) < 40:
                extra = next_sentence_after(a1)
                if extra and len(extra) >= 20:
                    topic = extra
                    source = "html_text"

        # External metadata goes into context, not topic
        if external_title:
            context = normalize_whitespace(external_title)
        if external_desc:
            desc = normalize_whitespace(external_desc).split(".")[0][:160]
            context = "{} | {}".format(context, desc).strip(" |")

        return topic[:180].strip(), context.strip(), source

    # Fallbacks
    if external_title and len(normalize_whitespace(external_title)) >= 18:
        return normalize_whitespace(external_title)[:180], normalize_whitespace(external_desc)[:160], "external_title"
    if external_desc and len(normalize_whitespace(external_desc)) >= 18:
        return normalize_whitespace(external_desc).split(".")[0][:180], "", "external_desc"
    return "", "", "none"


# ---------------------------------------------------------------------------
# Language detection (P1.3)
# ---------------------------------------------------------------------------


def detect_language(text):
    if not text or len(text) < 20:
        return "de"
    try:
        lang = detect(text)
        return lang
    except LangDetectException:
        return "de"


def add_language_prefix(context, topic):
    """If the topic/context appears non-German, prepend [Quelle: XX]."""
    sample = topic if len(topic) >= 40 else "{} {}".format(topic, context)
    lang = detect_language(sample)
    if lang != "de":
        prefix = "[Quelle: {}]".format(lang.upper())
        if context:
            return "{} {}".format(prefix, context)
        return prefix
    return context


# ---------------------------------------------------------------------------
# Hard-drop filters (P0.3)
# ---------------------------------------------------------------------------


def check_hard_drop(topic):
    """Return a drop_reason string if the row should be dropped, else None."""
    t = topic.strip()

    if len(t) < 18:
        return "too_short"

    if URL_ISH.search(t):
        return "url_ish"

    if MAPS_BOILER.search(t):
        return "maps_boilerplate"

    digit_count = sum(c.isdigit() for c in t)
    if len(t) > 0 and digit_count / len(t) > 0.18:
        return "digit_heavy"

    stripped = t.strip().lower()
    if BRAND_DOMAINS.match(stripped) and len(t) < 25:
        return "brand_domain"

    return None


# ---------------------------------------------------------------------------
# Quality scoring (P0.4)
# ---------------------------------------------------------------------------


def compute_quality_score(topic, context):
    q = 0.5

    # Content-word count (words that aren't stopwords/short)
    words = [w for w in topic.split() if len(w) > 2]
    if len(words) >= 4:
        q += 0.15

    # Contains quotes or colons
    if any(c in topic for c in ('"', "'", "\u201e", "\u201c", ":")):
        q += 0.10

    # Contains CVE or number+unit
    if re.search(r"CVE-|(\d+\s*(€|%|km|GB|MB|TB|°C|Mrd|Mio))", topic):
        q += 0.10

    # Named-entity-like tokens (capitalized, not sentence start)
    tokens = topic.split()
    ne_count = sum(1 for i, t in enumerate(tokens) if i > 0 and t[0:1].isupper() and len(t) > 2)
    if ne_count >= 2:
        q += 0.10

    # Context length
    if len(context) >= 40:
        q += 0.05

    # Penalties
    if GENERIC_PORTAL.search(topic):
        q -= 0.35

    sep_count = len(re.findall(r"[|•–—]", topic))
    if sep_count >= 2 and len(words) < 4:
        q -= 0.25

    if MAPS_BOILER.search(topic):
        q -= 0.40

    return max(0.0, min(1.0, q))


def quality_bucket(score):
    if score >= 0.70:
        return "high"
    if score >= 0.35:
        return "mid"
    if score >= 0.15:
        return "low"
    return "drop"


# ---------------------------------------------------------------------------
# Weighted sampling (P0.4)
# ---------------------------------------------------------------------------


def apply_weighted_sampling(rows):
    """Repeat rows based on quality bucket: high=3x, mid=1x, low=0.5x."""
    result = []
    for row in rows:
        bucket = row["quality_bucket"]
        if bucket == "high":
            result.extend([row] * 3)
        elif bucket == "mid":
            result.append(row)
        elif bucket == "low":
            # 0.5x: include with 50% probability
            if random.random() < 0.5:
                result.append(row)
    return result


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def pick_best_external(sources):
    """Return (title, description) from the best external source."""
    for source in (sources or []):
        title = normalize_whitespace(source.get("title"))
        desc = normalize_whitespace(source.get("description"))
        if title or desc:
            return title, desc
    return "", ""


def process_posts(raw_data):
    training_data = []
    stats = {
        "total_posts": 0,
        "skipped_short_comment": 0,
        "skipped_no_topic": 0,
        "dropped": {},
        "buckets": {"high": 0, "mid": 0, "low": 0},
        "sources": {},
    }

    for post_id, post in raw_data.items():
        stats["total_posts"] += 1

        target_comment = normalize_whitespace(post.get("content", ""))
        if len(target_comment) < MIN_COMMENT_LENGTH:
            stats["skipped_short_comment"] += 1
            continue

        content_html = post.get("contentHtml", "")
        sources = post.get("externalSources", []) or []
        ext_title, ext_desc = pick_best_external(sources)

        topic, context, topic_source = build_topic_context_from_html(
            content_html, ext_title, ext_desc
        )

        if not topic:
            stats["skipped_no_topic"] += 1
            continue

        # Hard-drop check (P0.3)
        drop_reason = check_hard_drop(topic)
        if drop_reason:
            stats["dropped"][drop_reason] = stats["dropped"].get(drop_reason, 0) + 1
            continue

        # Language prefix (P1.3)
        context = add_language_prefix(context, topic)

        # Quality scoring (P0.4)
        score = compute_quality_score(topic, context)
        bucket = quality_bucket(score)

        if bucket == "drop":
            stats["dropped"]["quality_drop"] = stats["dropped"].get("quality_drop", 0) + 1
            continue

        stats["buckets"][bucket] = stats["buckets"].get(bucket, 0) + 1
        stats["sources"][topic_source] = stats["sources"].get(topic_source, 0) + 1

        # Extract URL from first external source
        url = ""
        if sources:
            url = normalize_whitespace(sources[0].get("url", ""))

        training_data.append({
            "topic": topic,
            "context": context,
            "url": url,
            "target_comment": target_comment,
            "timestamp": post.get("timestamp"),
            "post_url": post.get("url"),
            "post_id": post_id,
            "topic_source": topic_source,
            "quality_score": round(score, 3),
            "quality_bucket": bucket,
        })

    return training_data, stats


def main():
    parser = argparse.ArgumentParser(description="Prepare Fefe training data with HTML-first extraction")
    parser.add_argument("--input", default="messages.json", help="Raw messages JSON")
    parser.add_argument("--output", default="prepared/fefe_training_data.json", help="Output path")
    parser.add_argument("--no-weighted-sampling", action="store_true", help="Disable weighted sampling (uniform)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    args = parser.parse_args()

    random.seed(args.seed)

    with open(args.input, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    training_data, stats = process_posts(raw_data)

    # Weighted sampling
    if not args.no_weighted_sampling:
        before_count = len(training_data)
        training_data = apply_weighted_sampling(training_data)
        print("Weighted sampling: {} -> {} rows".format(before_count, len(training_data)))

    random.shuffle(training_data)

    Path(args.output).parent.mkdir(exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(training_data, f, ensure_ascii=False, indent=2)

    # Report
    print("Total posts: {}".format(stats["total_posts"]))
    print("Skipped (short comment): {}".format(stats["skipped_short_comment"]))
    print("Skipped (no topic): {}".format(stats["skipped_no_topic"]))
    print("Dropped:")
    for reason, count in sorted(stats["dropped"].items(), key=lambda x: -x[1]):
        print("  {}: {}".format(reason, count))
    print("Quality buckets:")
    for bucket, count in sorted(stats["buckets"].items()):
        print("  {}: {}".format(bucket, count))
    print("Topic sources:")
    for source, count in sorted(stats["sources"].items(), key=lambda x: -x[1]):
        print("  {}: {}".format(source, count))
    print("Final training rows: {}".format(len(training_data)))


if __name__ == "__main__":
    main()
