## P0: Fix conditioning signal and make it measurable

### P0.1 Replace your topic extraction source of truth
**Rule:** `topic` must come from **FEFE’s own post HTML** (anchor text + nearby quote), not from `externalSources`.

**Why:** FEFE’s comment is conditioned on *his framing* (anchor text, rhetorical setup, blockquote), while external titles are often generic/boilerplate (Maps, portals, slogans).

#### Output schema changes
Add these fields to each row:
- **topic_final:** final topic used for training/inference
- **context_final:** final context used for training/inference
- **topic_source:** one of `html_anchor`, `html_anchor+blockquote`, `html_text`, `external_title`, `external_desc`
- **quality_score:** float in \([0,1]\)
- **quality_bucket:** `high|mid|low`
- **drop_reason:** optional string (if dropped)

---

### P0.2 Deterministic HTML-first extraction algorithm
Use this priority order **per post**:

1. **Primary external anchor text** (first `<a href="http(s)://...">` that is not `?ts=...`)
2. **Nearest `<blockquote>` after that anchor** (append short fragment if useful)
3. If anchor is **deictic** (“das hier”, “was das ist”, “hier”, “dies”): resolve by appending
   - **next sentence after the anchor**, else
   - **second external anchor text** in parentheses
4. If the URL is **Google Maps**: ignore external title/boilerplate and derive from surrounding FEFE text + place names
5. Fallback to `externalSources.title`, then `externalSources.description` (first sentence)

---

### P0.3 Hard-drop the worst rows (after HTML extraction)
Drop row if any:

- **Too short:** `len(topic_final.strip()) < 18`
- **URL-ish topic:** contains any of `http`, `www.`, `utm_`, `.de/`, `.com/`, `?`
- **Maps boilerplate topic:** matches (case-insensitive) any of:
  - `find local businesses`
  - `view maps`
  - `driving directions`
  - `google maps`
  - `postleitzahl | quelle`
- **Digit-heavy:** `digits / len(topic_final) > 0.18`
- **Pure brand/domain:** topic equals a known site name/domain and `< 25` chars (e.g. `derStandard.at`)

---

### P0.4 Score remaining rows and use weighted sampling
Compute `quality_score` and bucket:
- **high:** `q >= 0.70`
- **mid:** `0.35 <= q < 0.70`
- **low:** `0.15 <= q < 0.35`
- **drop:** `q < 0.15`

Training sampling:
- **high:** 3×
- **mid:** 1×
- **low:** 0.5× (keep some diversity, but don’t let it dominate)

---

### P0.5 Build a small benchmark set and a rubric
Create **300 fixed items** stratified by bucket:
- **100 high / 100 mid / 100 low**
- Ensure at least **50 EN-source** items

Rubric (0–3 each):
- **Style fidelity:** FEFE-ish dryness/irony/satire
- **Topical relevance:** depends on topic/context vs generic
- **Hallucination risk:** inventing specifics not in input

---

## P1: Extraction details that match FEFE’s structure

### P1.1 What goes into topic vs context
- **topic_final:** FEFE’s *frame* (anchor text + optional short quote)
- **context_final:** supporting grounding (source/domain, description, language hint, extra snippet)

**Do not** stuff everything into topic—keep it short and punchy.

---

### P1.2 Special handling rules

#### Deictic anchors
If anchor text matches:
- `das hier`, `dies`, `hier`, `was das`, `was das hier`

Then append:
- **next sentence after anchor** (up to 140 chars), else
- **second external anchor** in parentheses

#### Google Maps links
If URL contains `google.com/maps` or `google.de/maps`:
- **Never** use external title/description as topic
- Prefer:
  - nearest preceding sentence like “Wenn ihr euch das mal auf der Karte angucken wollt…”
  - place names from nearby text (capitalized tokens)
  - blockquote location lines (e.g. “Melitopol, südliche Ukraine.”)

---

### P1.3 Multilingual sources without changing prompt format
Detect language of extracted quote/snippet (cheap heuristic is fine). If non-DE:
- prepend to `context_final`:
  - `[Quelle: EN] ...` or `[Quelle: XX] ...`

This keeps your prompt structure identical—only field content changes.

---

## P2: Training changes only after P0/P1 are in place

### P2.1 Minimal training experiment sequence
Run these in order and stop when relevance improves:

1. **E0 baseline:** current pipeline
2. **E1 HTML-first + hard-drop:** uniform sampling, packing on
3. **E2 HTML-first + hard-drop + weighted sampling:** packing on
4. **E3 same as E2 but packing off:** test topical binding impact

If E2/E3 improves relevance materially, keep LoRA config as-is.

---

### P2.2 Recommended training knobs to try (only if needed)
- **Packing:** keep for throughput, but use **packing off** for relevance-sensitive runs
- **Epochs/LR:** after cleaning, try **2 epochs** with **LR 1e-5** (vs 1 epoch @ 2e-5)
- **Completion-only loss:** if your setup supports “train on assistant tokens only,” enable it (often helps conditioning)

---

## Concrete rules and thresholds

### Topic construction constraints
- **Max topic length:** 180 chars (trim)
- **Blockquote fragment:** 20–140 chars, append with `: `
- **Next sentence fragment:** up to 140 chars

### Quality score components
Use a simple additive score:

- Start `q = 0.5`
- Add:
  - `+0.15` if content-word count ≥ 4
  - `+0.10` if contains quotes or `:`
  - `+0.10` if contains `CVE-` or number+unit (`€`, `%`, `km`, `GB`, `°C`)
  - `+0.10` if 2+ named-entity-like tokens (capitalized, not sentence start)
  - `+0.05` if context_final length ≥ 40
- Subtract:
  - `-0.35` if matches generic/portal patterns
  - `-0.25` if separator soup (`| • –`) and low content words
  - `-0.40` if maps boilerplate detected (should be dropped anyway)

Clamp to \([0,1]\).

---

## Pseudocode for improved curation

```python
import re
from bs4 import BeautifulSoup

DEICTIC = re.compile(r"\b(das hier|dies|hier|was das|was das hier)\b", re.I)
MAPS_URL = re.compile(r"google\.(de|com)/maps", re.I)
MAPS_BOILER = re.compile(r"(find local businesses|view maps|driving directions|google maps|postleitzahl\s*\|\s*quelle)", re.I)

def is_external_link(a):
    href = (a.get("href") or "").strip()
    if not href: return False
    if href.startswith("?ts="): return False
    return href.startswith("http://") or href.startswith("https://")

def normalize_ws(s): return " ".join((s or "").split()).strip()

def first_external_anchors(soup):
    out = []
    for a in soup.find_all("a"):
        if is_external_link(a):
            out.append((a.get("href"), normalize_ws(a.get_text(" ", strip=True)), a))
    return out

def nearest_blockquote_after(a_tag, max_chars=140):
    node = a_tag
    for _ in range(20):
        node = getattr(node, "next_element", None)
        if node is None: break
        if getattr(node, "name", None) == "blockquote":
            return normalize_ws(node.get_text(" ", strip=True))[:max_chars]
    return ""

def next_sentence_after(a_tag, max_chars=140):
    node = a_tag
    buf = []
    for _ in range(60):
        node = getattr(node, "next_element", None)
        if node is None: break
        if isinstance(node, str):
            t = normalize_ws(node)
            if t:
                buf.append(t)
                joined = " ".join(buf)
                if joined.endswith((".", "!", "?")) or len(joined) >= max_chars:
                    return joined[:max_chars]
    return " ".join(buf)[:max_chars]

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
            topic = f"{topic}: {bq}"
            source = "html_anchor+blockquote"

        if DEICTIC.search(text1):
            extra = next_sentence_after(a1)
            if extra and len(extra) >= 20:
                topic = f"{text1} {extra}"
                source = "html_text"
            elif len(anchors) > 1 and len(anchors[1][1]) >= 20:
                topic = f"{text1} ({anchors[1][1]})"
                source = "html_text"

        # Maps special-case: if primary url is maps, topic must come from surrounding text
        if MAPS_URL.search(url1 or ""):
            # If topic looks like boilerplate, force deictic resolution path
            if MAPS_BOILER.search(topic) or len(topic) < 40:
                extra = next_sentence_after(a1)
                if extra and len(extra) >= 20:
                    topic = extra
                    source = "html_text"

        # Put external metadata into context (not topic)
        if external_title:
            context = f"{normalize_ws(external_title)}"
        if external_desc:
            desc = normalize_ws(external_desc).split(".")[0][:160]
            context = f"{context} | {desc}".strip(" |")

        return topic[:180].strip(), context.strip(), source

    # Fallbacks
    if external_title and len(normalize_ws(external_title)) >= 18:
        return normalize_ws(external_title)[:180], normalize_ws(external_desc)[:160], "external_title"
    if external_desc and len(normalize_ws(external_desc)) >= 18:
        return normalize_ws(external_desc).split(".")[0][:180], "", "external_desc"
    return "", "", "none"
```

---

## Minimal experiment matrix

| Experiment | Extraction | Filters | Sampling | Packing | Epochs | LR |
|---|---|---|---|---|---|---|
| **E0** | current | current | uniform | on | 1 | 2e-5 |
| **E1** | HTML-first | hard-drop | uniform | on | 1 | 2e-5 |
| **E2** | HTML-first | hard-drop + score | weighted | on | 1 | 2e-5 |
| **E3** | HTML-first | hard-drop + score | weighted | off | 1 | 2e-5 |

---
