"""Reading a document the way the Data Absorption tab shows it: lines, terms, topics and highlights (Request R1–R6).

The owner's reference is a news-analysis screen: a reader where words light up, a curved line runs from each lit word
to a topic list, and that topic's bar fills. Everything that drives that picture is computed here, offline, with no
model call: it has to keep pace with the reader (one line every second or so) and cost nothing while it does.

* ``split_lines`` — the sentences worth reading, in document order, at most ``limit`` of them.
* ``TopicModel`` — broad topics with weighted term lists. ``match`` finds topic terms in a line (the highlights);
  ``learn`` grows a topic's list from words that keep appearing next to its terms, so a run gets sharper as it reads.
* ``keyphrases`` — the terms a text is about (RAKE-style: phrases between stop words, scored by degree/frequency).
* ``derive_topics`` / ``topics_from_plan`` — topics for "only what I give you" and "study this prompt" runs.
* ``offline_facts`` / ``offline_summary`` — what to remember when no model is free to extract claims.

A model makes the facts and the report better (``absorb_engine``); nothing here needs one.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

_STOP = set("""a about above across after again against all almost along also although always am among an and another
any anyone anything are around as at away back be became because become becomes been before being below between both
but by can cannot could did do does doing done down during each either else enough etc even ever every few for from
further get gets getting give given gives go goes going gone got had has have having he her here hers herself him
himself his how however i if in into is it its itself just keep last least less let like likely made make makes making
many may maybe me might more most mostly much must my myself near need needs neither never new next no nor not now of
off often on once one only onto or other others our ours ourselves out over own per perhaps please put quite rather
really said same say says see seem seems several shall she should show shows since so some something sometimes still
such take takes than that the their theirs them themselves then there therefore these they thing things this those
though through thus to together too toward towards under until up upon us use used uses using very via was way ways
we well were what whatever when where whether which while who whom whose why will with within without would yet you
your yours yourself yourselves also able across first second third based using within including include includes
included however overall one two three four five six seven eight nine ten http https www com org html pdf fig figure
table et al paper papers study studies approach approaches method methods result results show shown propose proposed
present presents work works section introduction conclusion abstract""".split())

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9+#'\-]{1,40}")
#: Two or more capitalised words ("Alibaba Cloud", "Model Context Protocol") or acronyms with digits ("RTX 5080").
_ENTITY = re.compile(r"\b(?:[A-Z][a-zA-Z0-9]+(?:\s+(?:of|and|for|the|de|&)\s+|\s+)){1,3}[A-Z][a-zA-Z0-9]+\b|\b[A-Z]{2,}[0-9]*\b")
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])|\n{2,}|\n(?=\s*[-*•#]|\s*\d+[.)]\s)")

#: Broad topics for an "auto" run: what makes Nyx better at the work the owner gives it. ``terms`` seed the lexicon;
#: ``queries`` seed the searches. Codes are short so they fit a topic row, like the reference's EARN / CAPEX / REG.
DEFAULT_TOPICS: List[Dict[str, Any]] = [
    {"id": "agents", "code": "AGENT", "name": "AI agents & tool use",
     "terms": ["agent", "agents", "agentic", "tool use", "tool calling", "function calling", "planner", "planning", "multi-agent",
               "orchestration", "memory", "retrieval", "rag", "mcp", "model context protocol", "reasoning", "chain of thought",
               "reflection", "self-improvement", "workflow", "autonomous", "subagent", "delegation", "evaluation", "benchmark"],
     "queries": ["LLM agents tool use", "multi-agent orchestration", "retrieval augmented generation memory"]},
    {"id": "models", "code": "MODEL", "name": "Models, training & inference",
     "terms": ["llm", "language model", "transformer", "attention", "fine-tuning", "fine tuning", "lora", "quantization",
               "distillation", "inference", "tokens", "context window", "ollama", "gguf", "llama.cpp", "moe", "mixture of experts",
               "pretraining", "rlhf", "dpo", "embedding", "embeddings", "kv cache", "flash attention", "throughput", "latency",
               "open weights", "checkpoint", "parameters"],
     "queries": ["efficient LLM inference quantization", "small language model distillation", "local LLM ollama"]},
    {"id": "code", "code": "CODE", "name": "Coding & software",
     "terms": ["python", "typescript", "javascript", "react", "api", "fastapi", "refactor", "refactoring", "test", "tests",
               "testing", "bug", "debugging", "compiler", "runtime", "library", "framework", "repository", "git", "github",
               "code review", "type system", "concurrency", "async", "performance", "architecture", "database", "sql"],
     "queries": ["python best practices performance", "code generation benchmark", "react typescript patterns"]},
    {"id": "data", "code": "DATA", "name": "Data & analysis",
     "terms": ["dataset", "data", "statistics", "statistical", "regression", "correlation", "distribution", "mean", "median",
               "variance", "outlier", "anomaly", "clustering", "classification", "visualization", "chart", "spreadsheet",
               "table", "pandas", "forecast", "time series", "sampling", "survey", "metric", "metrics"],
     "queries": ["data analysis techniques anomaly detection", "time series forecasting methods"]},
    {"id": "finance", "code": "FIN", "name": "Finance & markets",
     "terms": ["revenue", "earnings", "margin", "margins", "cash flow", "balance sheet", "income statement", "valuation",
               "stock", "stocks", "market", "markets", "portfolio", "risk", "volatility", "interest rate", "inflation",
               "dividend", "etf", "bond", "yield", "guidance", "quarter", "fiscal", "ebitda", "capex", "debt", "equity"],
     "queries": ["financial statement analysis ratios", "portfolio risk management", "market volatility research"]},
    {"id": "science", "code": "SCI", "name": "Science & math",
     "terms": ["physics", "chemistry", "biology", "mathematics", "theorem", "proof", "equation", "probability", "algebra",
               "calculus", "geometry", "experiment", "hypothesis", "molecule", "energy", "quantum", "protein", "genome",
               "climate", "astronomy", "optimization", "matrix", "vector", "derivative", "integral"],
     "queries": ["recent breakthroughs physics", "mathematics proof techniques", "protein structure prediction"]},
    {"id": "design", "code": "DSGN", "name": "Design & UX",
     "terms": ["design", "user experience", "ux", "ui", "interface", "usability", "accessibility", "typography", "color",
               "layout", "prototype", "interaction", "animation", "motion", "human interface guidelines", "contrast",
               "navigation", "component", "design system", "visual hierarchy"],
     "queries": ["user interface design accessibility", "design systems best practices"]},
    {"id": "hardware", "code": "HW", "name": "Hardware & devices",
     "terms": ["gpu", "cpu", "npu", "vram", "memory", "chip", "semiconductor", "nvidia", "amd", "intel", "arm", "cuda",
               "microcontroller", "arduino", "raspberry pi", "sensor", "battery", "thermal", "power", "pcb", "circuit",
               "firmware", "fpga", "laptop", "server"],
     "queries": ["GPU memory efficient deep learning", "microcontroller projects sensors"]},
    {"id": "security", "code": "SEC", "name": "Security & privacy",
     "terms": ["security", "privacy", "vulnerability", "exploit", "encryption", "authentication", "authorization",
               "prompt injection", "jailbreak", "malware", "phishing", "sandbox", "threat", "attack", "defense", "cve",
               "zero-day", "password", "key management", "compliance"],
     "queries": ["prompt injection defenses LLM", "application security best practices"]},
    {"id": "world", "code": "NEWS", "name": "News & world",
     "terms": ["government", "policy", "regulation", "election", "economy", "company", "companies", "announced", "launch",
               "acquisition", "lawsuit", "court", "country", "global", "industry", "startup", "funding", "report"],
     "queries": ["technology industry news this week", "AI regulation policy"]},
]


def normalize(term: str) -> str:
    return re.sub(r"\s+", " ", (term or "").strip().lower().strip(".,;:!?()[]{}\"'"))


def words(text: str) -> List[str]:
    return [w.lower().strip("'-") for w in _WORD.findall(text or "")]


def content_words(text: str) -> List[str]:
    return [w for w in words(text) if len(w) > 2 and w not in _STOP and not w.isdigit()]


def estimate_tokens(text: str) -> int:
    return max(1, round(len(text or "") / 3.8))


# ---------------------------------------------------------------------------
# Lines
# ---------------------------------------------------------------------------


def _strip_math(text: str) -> str:
    """Drop LaTeX blocks such as Wikipedia's ``{\\displaystyle x_i}`` — formulas are not words to learn."""
    out, index = [], 0
    while index < len(text):
        start = text.find("{\\displaystyle", index)
        if start == -1:
            out.append(text[index:])
            break
        out.append(text[index:start])
        depth, position = 0, start
        while position < len(text):
            if text[position] == "{":
                depth += 1
            elif text[position] == "}":
                depth -= 1
                if depth == 0:
                    position += 1
                    break
            position += 1
        index = position
    cleaned = " ".join(out)
    cleaned = re.sub(r"\\(?:displaystyle|mathrm|mathbf|text|frac|sum|prod|sqrt|cdot|times)\b", " ", cleaned)
    return re.sub(r"\$\$?[^$]{0,400}\$\$?", " ", cleaned)


def _clean(text: str) -> str:
    text = _strip_math(text or "")
    text = re.sub(r"```.*?```", " ", text, flags=re.S)                 # code blocks read badly as prose
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)                  # markdown images
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)               # markdown links → their words
    text = re.sub(r"https?://\S+|www\.\S+", " ", text)                  # bare addresses are not something to learn
    text = re.sub(r"^\s*=+\s*[^=\n]{1,80}\s*=+\s*$", " ", text, flags=re.M)   # wiki section headings are not sentences
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t ]+", " ", text)
    return text.strip()


def _informative(line: str) -> bool:
    letters = sum(ch.isalpha() for ch in line)
    return letters >= 25 and letters / max(1, len(line)) >= 0.55 and len(content_words(line)) >= 4


def split_lines(text: str, limit: int = 24, max_chars: int = 260) -> List[str]:
    """The sentences worth reading, in order. Long sentences are cut at a word; link lists and tables are skipped."""
    pieces: List[str] = []
    for raw in _SENTENCE.split(_clean(text)):
        piece = re.sub(r"\s+", " ", raw).strip(" -*•#\t")
        while len(piece) > max_chars:
            cut = piece.rfind(" ", 0, max_chars)
            cut = cut if cut > max_chars // 2 else max_chars
            pieces.append(piece[:cut].strip())
            piece = piece[cut:].strip()
        if piece:
            pieces.append(piece)
    lines = [p for p in pieces if _informative(p)]
    seen: Set[str] = set()
    unique = []
    for line in lines:
        key = normalize(line)[:120]
        if key not in seen:
            seen.add(key)
            unique.append(line)
    if len(unique) <= limit:
        return unique
    # Too many: keep the densest ones but read them in the document's order.
    density = [(len(set(content_words(line))) / (1 + len(line) / 90), index) for index, line in enumerate(unique)]
    keep = sorted(index for _, index in sorted(density, reverse=True)[:limit])
    return [unique[i] for i in keep]


# ---------------------------------------------------------------------------
# Key phrases
# ---------------------------------------------------------------------------


def keyphrases(text: str, limit: int = 12) -> List[str]:
    """RAKE-style: runs of content words between stop words, scored by word degree over frequency."""
    candidates: List[List[str]] = []
    for sentence in re.split(r"[.!?;:\n,()\[\]]", _strip_math(text or "")):
        run: List[str] = []
        for word in words(sentence):
            if word in _STOP or len(word) < 3 or word.isdigit():
                if run:
                    candidates.append(run)
                run = []
            else:
                run.append(word)
        if run:
            candidates.append(run)
    frequency: Counter = Counter()
    degree: Counter = Counter()
    for run in candidates:
        run = run[:4]
        for word in run:
            frequency[word] += 1
            degree[word] += len(run) - 1
    scores: Dict[str, float] = {}
    phrase_counts: Counter = Counter(" ".join(run[:4]) for run in candidates)
    for phrase, count in phrase_counts.items():
        parts = phrase.split()
        score = sum((degree[w] + frequency[w]) / frequency[w] for w in parts)
        scores[phrase] = score * (1 + math.log(count)) if len(parts) > 1 else frequency[phrase] * 1.2
    ranked = sorted(scores.items(), key=lambda item: -item[1])
    out: List[str] = []
    for phrase, _score in ranked:
        if len(phrase) < 4 or any(phrase in existing or existing in phrase for existing in out):
            continue
        out.append(phrase)
        if len(out) >= limit:
            break
    return out


def entities(text: str, limit: int = 8) -> List[str]:
    found: List[str] = []
    for match in _ENTITY.finditer(text or ""):
        value = match.group(0).strip()
        if value.lower() in _STOP or len(value) < 2:
            continue
        if value not in found:
            found.append(value)
        if len(found) >= limit:
            break
    return found


# ---------------------------------------------------------------------------
# Topics
# ---------------------------------------------------------------------------


def code_for(name: str, used: Iterable[str] = ()) -> str:
    """A short upper-case code for a topic row: "Cloud & enterprise demand" → "CLOUD"."""
    taken = {u.upper() for u in used}
    parts = [w for w in re.findall(r"[A-Za-z0-9]+", name or "") if w.lower() not in _STOP] or ["TOPIC"]
    options = [parts[0][:5].upper(), "".join(p[0] for p in parts[:4]).upper(), (parts[0][:3] + (parts[1][:2] if len(parts) > 1 else "")).upper()]
    for option in options:
        if len(option) >= 2 and option not in taken:
            return option
    base = options[0][:4] or "T"
    for n in range(2, 99):
        if f"{base}{n}" not in taken:
            return f"{base}{n}"
    return base


class TopicModel:
    """Weighted term lists per topic, matched against lines and grown while reading."""

    MAX_TERMS = 160

    def __init__(self, topics: Sequence[Dict[str, Any]]) -> None:
        self.topics: List[Dict[str, Any]] = []
        for index, topic in enumerate(topics):
            terms = topic.get("terms") or {}
            weights = dict(terms) if isinstance(terms, dict) else {normalize(t): 1.0 for t in terms if normalize(t)}
            self.topics.append({
                "id": str(topic.get("id") or f"t{index}"), "code": str(topic.get("code") or code_for(topic.get("name", ""))),
                "name": str(topic.get("name") or topic.get("id") or f"Topic {index + 1}"), "color": int(topic.get("color", index)) % 10,
                "terms": weights, "queries": list(topic.get("queries") or []), "count": int(topic.get("count", 0)),
                "docs": int(topic.get("docs", 0)), "gain": float(topic.get("gain", 0.0)),
            })
        self._compile()

    def _compile(self) -> None:
        entries: List[Tuple[str, str, float]] = []
        for topic in self.topics:
            for term, weight in topic["terms"].items():
                if weight >= 0.5:  # a word seen once next to a topic is a candidate, not yet a highlight
                    entries.append((term, topic["id"], weight))
        # Longest first, so "flash attention" wins over "attention".
        entries.sort(key=lambda e: (-len(e[0]), -e[2]))
        self._owner: Dict[str, Tuple[str, float]] = {}
        for term, topic_id, weight in entries:
            current = self._owner.get(term)
            if current is None or weight > current[1]:
                self._owner[term] = (topic_id, weight)
        terms = sorted(self._owner, key=len, reverse=True)
        if terms:
            pattern = "|".join(r"[\s-]+".join(re.escape(part) for part in t.split(" ")) for t in terms[:1500])
            self._regex: Optional[re.Pattern] = re.compile(rf"(?<![A-Za-z0-9])(?:{pattern})(?![A-Za-z0-9])", re.I)
        else:
            self._regex = None

    def by_id(self, topic_id: str) -> Optional[Dict[str, Any]]:
        return next((t for t in self.topics if t["id"] == topic_id), None)

    def match(self, line: str, max_spans: int = 8) -> List[Dict[str, Any]]:
        """Highlights: ``[{"s", "e", "term", "topic"}]`` in line order, no overlaps."""
        spans: List[Dict[str, Any]] = []
        if self._regex is not None:
            for found in self._regex.finditer(line or ""):
                term = normalize(re.sub(r"[\s-]+", " ", found.group(0)))
                owner = self._owner.get(term) or self._owner.get(term.replace(" ", "-"))
                if owner is None:
                    continue
                spans.append({"s": found.start(), "e": found.end(), "term": term, "topic": owner[0]})
        # Names nobody's lexicon knows yet are still worth lighting up, without a topic.
        for match in _ENTITY.finditer(line or ""):
            if any(not (match.end() <= s["s"] or match.start() >= s["e"]) for s in spans):
                continue
            value = match.group(0)
            if value.lower() in _STOP or len(value) < 3:
                continue
            spans.append({"s": match.start(), "e": match.end(), "term": value, "topic": None})
        spans.sort(key=lambda s: s["s"])
        if len(spans) > max_spans:
            topical = [s for s in spans if s["topic"]][:max_spans]
            spans = sorted(topical + [s for s in spans if not s["topic"]][: max(0, max_spans - len(topical))], key=lambda s: s["s"])
        return spans

    def vote(self, spans: Sequence[Dict[str, Any]]) -> Dict[str, float]:
        """How strongly a line (or a whole document) speaks to each topic, as shares that add up to 1."""
        weights: Dict[str, float] = defaultdict(float)
        for span in spans:
            if span.get("topic"):
                weights[span["topic"]] += self._owner.get(span["term"], (span["topic"], 1.0))[1]
        total = sum(weights.values())
        return {k: round(v / total, 3) for k, v in weights.items()} if total else {}

    def count(self, spans: Sequence[Dict[str, Any]]) -> None:
        for span in spans:
            topic = self.by_id(span.get("topic") or "")
            if topic is not None:
                topic["count"] += 1

    def learn(self, line: str, spans: Sequence[Dict[str, Any]], rate: float = 0.25) -> List[Tuple[str, str]]:
        """Words that sit next to a topic's terms join that topic's list (weakly). Returns the ``(topic, term)`` added."""
        vote = self.vote(spans)
        if not vote:
            return []
        topic_id, share = max(vote.items(), key=lambda kv: kv[1])
        if share < 0.6:
            return []
        topic = self.by_id(topic_id)
        if topic is None:
            return []
        added = []
        matched = {s["term"] for s in spans}
        for phrase in keyphrases(line, limit=3):
            if phrase in matched or phrase in self._owner or len(phrase) > 40:
                continue
            weight = topic["terms"].get(phrase, 0.0) + rate
            topic["terms"][phrase] = round(weight, 3)
            if weight >= 0.5 and phrase not in self._owner:  # seen twice: now it lights up too
                added.append((topic_id, phrase))
        if len(topic["terms"]) > self.MAX_TERMS:
            topic["terms"] = dict(sorted(topic["terms"].items(), key=lambda kv: -kv[1])[: self.MAX_TERMS])
        if added:
            self._compile()
        return added

    def top_terms(self, topic_id: str, limit: int = 6) -> List[str]:
        topic = self.by_id(topic_id)
        if topic is None:
            return []
        return [t for t, _ in sorted(topic["terms"].items(), key=lambda kv: -kv[1])[:limit]]

    def as_list(self) -> List[Dict[str, Any]]:
        return [{**{k: v for k, v in t.items() if k != "terms"}, "terms": dict(sorted(t["terms"].items(), key=lambda kv: -kv[1])[:60])}
                for t in self.topics]


def novelty(terms: Iterable[str], known: Set[str]) -> float:
    unique = {normalize(t) for t in terms if normalize(t)}
    if not unique:
        return 0.0
    return round(sum(1 for t in unique if t not in known) / len(unique), 3)


def derive_topics(texts: Sequence[str], k: int = 6) -> List[Dict[str, Any]]:
    """Topics for the owner's own documents: key phrases grouped by the documents and sentences they share."""
    phrase_docs: Dict[str, Set[int]] = defaultdict(set)
    phrase_score: Counter = Counter()
    sentences: List[Set[str]] = []
    for index, text in enumerate(texts):
        for phrase in keyphrases(text, limit=25):
            phrase_docs[phrase].add(index)
            phrase_score[phrase] += 1
        for line in split_lines(text, limit=80):
            sentences.append(set(content_words(line)))
    seeds = [p for p, _ in phrase_score.most_common(60)]
    groups: List[Dict[str, Any]] = []
    used: Set[str] = set()
    for seed in seeds:
        if seed in used or len(groups) >= k:
            continue
        seed_words = set(seed.split())
        members = [seed]
        for other in seeds:
            if other in used or other == seed:
                continue
            other_words = set(other.split())
            together = sum(1 for s in sentences if seed_words & s and other_words & s)
            if seed_words & other_words or together >= 2:
                members.append(other)
        used.update(members)
        name = seed.title() if len(seed) > 3 else seed.upper()
        groups.append({"id": re.sub(r"[^a-z0-9]+", "-", seed)[:24].strip("-") or f"t{len(groups)}", "name": name,
                       "terms": members[:20] + sorted(seed_words - _STOP)[:4], "queries": [seed]})
    if not groups:
        groups = [{"id": "document", "name": "The documents", "terms": seeds[:20] or ["document"], "queries": []}]
    taken: List[str] = []
    for group in groups:
        group["code"] = code_for(group["name"], taken)
        taken.append(group["code"])
    return groups


def topics_from_plan(prompt: str, plan: Optional[Sequence[Dict[str, Any]]] = None, related: Sequence[str] = ()) -> List[Dict[str, Any]]:
    """Topics for "study this": the model's plan when there is one, otherwise the prompt's own words plus related concepts."""
    topics: List[Dict[str, Any]] = []
    taken: List[str] = []
    for item in plan or []:
        name = str(item.get("name") or "").strip()[:60]
        terms = [normalize(t) for t in (item.get("terms") or []) if normalize(t)]
        if not name or not terms:
            continue
        code = str(item.get("code") or "").upper()[:6] or code_for(name, taken)
        if code in taken:
            code = code_for(name, taken)
        taken.append(code)
        topics.append({"id": re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:24] or f"t{len(topics)}", "code": code, "name": name,
                       "terms": terms[:40], "queries": [str(q)[:120] for q in (item.get("queries") or [])][:4] or [name]})
        if len(topics) >= 8:
            break
    if topics:
        return topics
    phrases = keyphrases(prompt, limit=6) or content_words(prompt)[:4] or [prompt.strip()[:40] or "topic"]
    extra = [normalize(r) for r in related if normalize(r)]
    for phrase in phrases[:5]:
        name = phrase.title()
        code = code_for(name, taken)
        taken.append(code)
        topics.append({"id": re.sub(r"[^a-z0-9]+", "-", phrase)[:24].strip("-") or f"t{len(topics)}", "code": code, "name": name,
                       "terms": [phrase, *phrase.split(), *extra[:10]], "queries": [f"{phrase}", f"{prompt.strip()[:80]} {phrase}".strip()]})
    return topics


# ---------------------------------------------------------------------------
# Without a model
# ---------------------------------------------------------------------------


def offline_facts(lines: Sequence[str], spans: Sequence[Sequence[Dict[str, Any]]], limit: int = 5) -> List[Dict[str, Any]]:
    """The lines that carry the most topic terms and names, as memories worth keeping."""
    scored = []
    for index, line in enumerate(lines):
        line_spans = spans[index] if index < len(spans) else []
        topical = [s for s in line_spans if s.get("topic")]
        score = len(topical) * 1.5 + len(line_spans) * 0.5 + (1 if re.search(r"\d", line) else 0)
        if score <= 0:
            continue
        topic = Counter(s["topic"] for s in topical).most_common(1)[0][0] if topical else None
        scored.append((score, index, line, topic))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [{"text": line, "topic": topic, "line": index} for _score, index, line, topic in sorted(scored[:limit], key=lambda x: x[1])]


def offline_summary(lines: Sequence[str], sentences: int = 2) -> str:
    if not lines:
        return ""
    ranked = sorted(range(len(lines)), key=lambda i: (-len(set(content_words(lines[i]))), i))[:sentences]
    return " ".join(lines[i] for i in sorted(ranked))[:500]
