#!/usr/bin/env python3
"""News monitoring bot.

Fetches articles from a curated list of Brazilian business/legal news outlets,
filters them by a set of corporate/tax/regulatory keywords, removes near-duplicate
stories using a lightweight NLP similarity heuristic, and writes a Markdown
report into the ``reports/`` folder.

Designed to run unattended on GitHub Actions, so it never raises on a single
failing source: every fetch is wrapped and logged, and the report is always
produced (even if empty).
"""

from __future__ import annotations

import logging
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable

import feedparser
import requests
from bs4 import BeautifulSoup

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
)
logger = logging.getLogger("news-bot")

# Pretend to be a normal browser so feeds/sites don't 403 the Actions runner.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
REQUEST_TIMEOUT = 25  # seconds
REQUEST_DELAY = 1.0   # polite delay between sources

# Each source exposes one or more RSS/Atom feeds. We try them in order and use
# every entry we can parse. HTML scraping is used as a fallback for sources
# without a usable feed.
SOURCES: dict[str, dict] = {
    "Valor Econômico": {
        "feeds": ["https://pox.globo.com/rss/valor/"],
    },
    "JOTA": {
        "feeds": ["https://www.jota.info/feed"],
    },
    "Brazil Journal": {
        "feeds": ["https://braziljournal.com/feed/"],
    },
    "Poder360": {
        "feeds": ["https://www.poder360.com.br/feed/"],
    },
    "Reuters Brasil": {
        "feeds": [
            "https://www.reutersagency.com/feed/?best-sectors=business-finance&post_type=best",
        ],
        "html": "https://www.reuters.com/world/americas/",
    },
    "InfoMoney": {
        "feeds": ["https://www.infomoney.com.br/feed/"],
    },
    "NeoFeed": {
        "feeds": ["https://neofeed.com.br/feed/"],
    },
    "Exame": {
        "feeds": ["https://exame.com/feed/"],
    },
    # --- NOVAS FONTES INSTITUCIONAIS (DESCENTRALIZADAS) ---
    "FGV IBRE": {
        "feeds": [],
        "html": "https://portalibre.fgv.br/",
    },
    "Agência CNI": {
        "feeds": [],
        "html": "https://noticias.portaldaindustria.com.br/noticias/",
    },
    "Serasa Experian": {
        "feeds": [],
        "html": "https://www.serasaexperian.com.br/sala-de-imprensa/",
    },
}

# Keywords to monitor. Each entry is the canonical label plus regex-ready
# variants (accent-insensitive matching is handled by normalisation).
KEYWORDS: dict[str, list[str]] = {
    "CARF": [r"\bcarf\b", r"conselho administrativo de recursos fiscais"],
    "STF": [r"\bstf\b", r"supremo tribunal federal", r"repercussao geral"],
    "STJ": [r"\bstj\b", r"superior tribunal de justica", r"recurso especial", r"recurso repetitivo"],
    "Congresso & Legislação": [r"congresso nacional", r"\bcamara dos deputados\b", r"\bsenado\b", r"projeto de lei", r"\bmedida provisoria\b", r"reforma tributaria"],
    "M&A e Societário": [r"\bm&a\b", r"\bm e a\b", r"fusoes", r"aquisic", r"joint venture", r"private equity"],
    "Recuperação & Crédito": [r"recuperacao judicial", r"\binadimplencia\b", r"falencia", r"credito corporativo"],
    "Mercado de Capitais": [r"\bcvm\b", r"valores mobiliarios", r"\bipo\b", r"follow on", r"debenture[s]?"],
    "Balanços e Resultados": [r"\bbalanco[s]?\b", r"resultado[s]? trimestral", r"\blucro liquido\b", r"\bebitda\b"],
    "Regulação & Concorrência": [r"regulac", r"\bgovernanca\b", r"compliance", r"\bcade\b", r"defesa economica"],
    "Macroeconomia e Juros": [r"\bjuros\b", r"\bselic\b", r"\bcopom\b", r"politica monetaria", r"\bipca\b"],
}

REPORTS_DIR = Path(__file__).resolve().parent / "reports"
SIMILARITY_THRESHOLD = 0.82  # titles more similar than this are deduplicated


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #

@dataclass
class Article:
    title: str
    link: str
    source: str
    summary: str = ""
    published: str = ""
    matched_keywords: list[str] = field(default_factory=list)

    @property
    def haystack(self) -> str:
        """Normalised text used for keyword matching."""
        return normalize(f"{self.title} {self.summary}")


# --------------------------------------------------------------------------- #
# Text utilities (basic NLP)
# --------------------------------------------------------------------------- #

def normalize(text: str) -> str:
    """Lowercase, strip accents and collapse whitespace for robust matching."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


_STOPWORDS = {
    "a", "o", "os", "as", "de", "da", "do", "das", "dos", "e", "em", "no", "na",
    "nos", "nas", "um", "uma", "para", "por", "com", "que", "se", "ao", "aos",
    "sobre", "the", "of", "to", "in", "and", "for",
}


def _signature(title: str) -> set[str]:
    """Token set of a title without stopwords — used for fast dedup pre-check."""
    tokens = re.findall(r"[a-z0-9]+", normalize(title))
    return {t for t in tokens if t not in _STOPWORDS and len(t) > 2}


def _similar(a: str, b: str) -> float:
    """Hybrid similarity: Jaccard on token sets blended with sequence ratio."""
    sa, sb = _signature(a), _signature(b)
    if sa and sb:
        jaccard = len(sa & sb) / len(sa | sb)
    else:
        jaccard = 0.0
    ratio = SequenceMatcher(None, normalize(a), normalize(b)).ratio()
    return max(jaccard, ratio)


def deduplicate(articles: list[Article]) -> list[Article]:
    """Drop near-duplicate articles, keeping the first occurrence.

    Cross-source reporting of the same story is common; we compare normalised
    titles and treat anything above ``SIMILARITY_THRESHOLD`` as a duplicate.
    """
    unique: list[Article] = []
    for art in articles:
        if any(_similar(art.title, kept.title) >= SIMILARITY_THRESHOLD for kept in unique):
            logger.debug("Dropping duplicate: %s", art.title)
            continue
        unique.append(art)
    removed = len(articles) - len(unique)
    if removed:
        logger.info("Deduplication removed %d near-duplicate article(s).", removed)
    return unique


# --------------------------------------------------------------------------- #
# Keyword matching
# --------------------------------------------------------------------------- #

_COMPILED_KEYWORDS = {
    label: [re.compile(p) for p in patterns] for label, patterns in KEYWORDS.items()
}


def match_keywords(article: Article) -> list[str]:
    text = article.haystack
    matched = [
        label
        for label, patterns in _COMPILED_KEYWORDS.items()
        if any(p.search(text) for p in patterns)
    ]
    return matched


# --------------------------------------------------------------------------- #
# Fetching
# --------------------------------------------------------------------------- #

def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "pt-BR,pt;q=0.9"})
    return s


def fetch_feed(source: str, url: str, session: requests.Session) -> list[Article]:
    articles: list[Article] = []
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
    except Exception as exc:  # noqa: BLE001 — never let one source kill the run
        logger.warning("Feed failed for %s (%s): %s", source, url, exc)
        return articles

    for entry in parsed.entries:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue
        summary_raw = entry.get("summary") or entry.get("description") or ""
        summary = BeautifulSoup(summary_raw, "lxml").get_text(" ", strip=True)
        published = entry.get("published") or entry.get("updated") or ""
        articles.append(
            Article(title=title, link=link, source=source, summary=summary, published=published)
        )
    logger.info("%-16s | %3d entries from feed", source, len(articles))
    return articles


def fetch_html(source: str, url: str, session: requests.Session) -> list[Article]:
    """Best-effort fallback: pull anchor headlines from a landing page."""
    articles: list[Article] = []
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "lxml")
    except Exception as exc:  # noqa: BLE001
        logger.warning("HTML fallback failed for %s (%s): %s", source, url, exc)
        return articles

    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        title = anchor.get_text(" ", strip=True)
        link = anchor["href"]
        if len(title) < 30 or link in seen:
            continue
        if link.startswith("/"):
            link = requests.compat.urljoin(url, link)
        if not link.startswith("http"):
            continue
        seen.add(link)
        articles.append(Article(title=title, link=link, source=source))
    logger.info("%-16s | %3d headlines from HTML fallback", source, len(articles))
    return articles


def collect_articles() -> list[Article]:
    session = _session()
    collected: list[Article] = []
    for source, cfg in SOURCES.items():
        source_articles: list[Article] = []
        for feed_url in cfg.get("feeds", []):
            source_articles.extend(fetch_feed(source, feed_url, session))
            time.sleep(REQUEST_DELAY)
        # Use HTML fallback only if feeds yielded nothing.
        if not source_articles and cfg.get("html"):
            source_articles.extend(fetch_html(source, cfg["html"], session))
            time.sleep(REQUEST_DELAY)
        collected.extend(source_articles)
    logger.info("Collected %d article(s) total before filtering.", len(collected))
    return collected


# --------------------------------------------------------------------------- #
# Report generation
# --------------------------------------------------------------------------- #

def build_report(articles: list[Article], generated_at: datetime) -> str:
    stamp = generated_at.strftime("%d/%m/%Y %H:%M UTC")
    lines: list[str] = []
    lines.append(f"# 📰 Monitoramento Corporativo — {stamp}")
    lines.append("")
    lines.append(
        f"Relatório gerado automaticamente. **{len(articles)}** notícia(s) "
        f"relevante(s) encontrada(s) em **{len(SOURCES)}** fontes."
    )
    lines.append("")

    if not articles:
        lines.append("_Nenhuma notícia correspondente às palavras-chave foi encontrada nesta execução._")
        lines.append("")
        return "\n".join(lines)

    # Summary table of keyword hits.
    counts: dict[str, int] = {label: 0 for label in KEYWORDS}
    for art in articles:
        for kw in art.matched_keywords:
            counts[kw] += 1
    lines.append("## 🔎 Resumo por palavra-chave")
    lines.append("")
    lines.append("| Palavra-chave | Ocorrências |")
    lines.append("| --- | ---: |")
    for label, count in sorted(counts.items(), key=lambda kv: kv[1], reverse=True):
        if count:
            lines.append(f"| {label} | {count} |")
    lines.append("")

    # Group articles by source.
    lines.append("## 🗞️ Notícias por fonte")
    lines.append("")
    by_source: dict[str, list[Article]] = {}
    for art in articles:
        by_source.setdefault(art.source, []).append(art)

    for source in SOURCES:
        items = by_source.get(source)
        if not items:
            continue
        lines.append(f"### {source} ({len(items)})")
        lines.append("")
        for art in items:
            tags = " ".join(f"`{kw}`" for kw in art.matched_keywords)
            lines.append(f"- [{art.title}]({art.link})")
            meta = []
            if art.published:
                meta.append(art.published)
            if tags:
                meta.append(tags)
            if meta:
                lines.append(f"  - {' · '.join(meta)}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("_Gerado por `scraper.py` via GitHub Actions._")
    lines.append("")
    return "\n".join(lines)


def write_report(content: str, generated_at: datetime) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"report_{generated_at.strftime('%Y-%m-%d_%H%M')}.md"
    path = REPORTS_DIR / filename
    path.write_text(content, encoding="utf-8")
    logger.info("Report written to %s", path)
    return path


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def filter_articles(articles: Iterable[Article]) -> list[Article]:
    relevant: list[Article] = []
    for art in articles:
        matched = match_keywords(art)
        if matched:
            art.matched_keywords = matched
            relevant.append(art)
    logger.info("%d article(s) matched the keyword filter.", len(relevant))
    return relevant


def main() -> None:
    generated_at = datetime.now(timezone.utc)
    logger.info("Starting news monitoring run at %s", generated_at.isoformat())

    raw = collect_articles()
    relevant = filter_articles(raw)
    unique = deduplicate(relevant)

    report = build_report(unique, generated_at)
    write_report(report, generated_at)

    logger.info("Run complete: %d relevant unique article(s).", len(unique))


if __name__ == "__main__":
    main()
