"""Lightweight keyword retrieval over the local dealership knowledge base."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from django.conf import settings


TOKEN_RE = re.compile(r"[a-zа-яё0-9][a-zа-яё0-9-]+", re.IGNORECASE)
STOP_WORDS = {
    "авто",
    "автомобиль",
    "будет",
    "вас",
    "ваш",
    "весь",
    "где",
    "для",
    "есть",
    "ещё",
    "или",
    "как",
    "клиент",
    "клиента",
    "мне",
    "можно",
    "мой",
    "на",
    "надо",
    "наш",
    "нужно",
    "ответ",
    "ответа",
    "подскажите",
    "пожалуйста",
    "при",
    "про",
    "сделка",
    "так",
    "что",
    "это",
}


@dataclass(frozen=True)
class KnowledgeChunk:
    """A searchable excerpt with a human-readable source label."""

    source: str
    text: str


def retrieve_knowledge_context(query: str, *, focus_query: str = "") -> str:
    """Return bounded relevant excerpts, or an empty string when KB is disabled."""

    if not getattr(settings, "AI_KB_ENABLED", True):
        return ""

    query_terms = _terms(query)
    focus_terms = _terms(focus_query)
    if not query_terms:
        return ""

    ranked: list[tuple[int, int, KnowledgeChunk]] = []
    for index, chunk in enumerate(_load_chunks()):
        chunk_terms = _terms(chunk.text)
        overlap = query_terms & chunk_terms
        if not overlap:
            continue
        focus_overlap = focus_terms & chunk_terms
        score = sum(3 if len(term) >= 6 else 1 for term in overlap)
        score += sum(30 if len(term) >= 4 else 10 for term in focus_overlap)
        ranked.append((score, -index, chunk))

    ranked.sort(reverse=True, key=lambda item: (item[0], item[1]))
    max_chunks = max(1, getattr(settings, "AI_KB_MAX_CHUNKS", 5))
    max_chars = max(500, getattr(settings, "AI_KB_MAX_CHARS", 6000))
    selected: list[str] = []
    used = 0
    for _, _, chunk in ranked[:max_chunks]:
        rendered = f"Источник: {chunk.source}\n{chunk.text.strip()}"
        remaining = max_chars - used
        if remaining <= 0:
            break
        selected.append(rendered[:remaining])
        used += len(rendered)

    return "\n\n".join(selected)


def _terms(text: str) -> set[str]:
    normalized = (text or "").lower().replace("ё", "е")
    return {token for token in TOKEN_RE.findall(normalized) if len(token) >= 2 and token not in STOP_WORDS}


@lru_cache(maxsize=1)
def _load_chunks() -> tuple[KnowledgeChunk, ...]:
    kb_dir = Path(settings.BASE_DIR) / "chatbot_context"
    chunks: list[KnowledgeChunk] = []
    chunks.extend(_profile_chunks(kb_dir / "salon_profile.json"))
    chunks.extend(_markdown_sections(kb_dir / "faq.md", heading_prefix="### ", source_prefix="FAQ"))
    chunks.extend(_catalog_lines(kb_dir / "cars_catalog.md"))
    return tuple(chunks)


def _profile_chunks(path: Path) -> list[KnowledgeChunk]:
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    chunks = [
        KnowledgeChunk(
            source="Профиль салона",
            text=(
                f"{profile.get('name', '')}. Адрес: {profile.get('address', '')}. "
                f"Телефон: {profile.get('phone', '')}. Часы работы: {profile.get('hours', '')}. "
                f"Сайт: {profile.get('website', '')}. Услуги: {', '.join(profile.get('services', []))}. "
                f"Важно: {profile.get('disclaimer', '')}"
            ),
        )
    ]
    for key, title in (("credit", "Кредит"), ("trade_in", "Trade-in"), ("buyout", "Выкуп"), ("used_cars", "Авто с пробегом")):
        value = profile.get(key)
        if value:
            chunks.append(KnowledgeChunk(source=f"Профиль салона: {title}", text=json.dumps(value, ensure_ascii=False)))
    return chunks


def _markdown_sections(path: Path, *, heading_prefix: str, source_prefix: str) -> list[KnowledgeChunk]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    chunks: list[KnowledgeChunk] = []
    title = ""
    body: list[str] = []
    for line in lines:
        if line.startswith(heading_prefix):
            if title and body:
                chunks.append(KnowledgeChunk(source=f"{source_prefix}: {title}", text="\n".join(body).strip()))
            title = line.removeprefix(heading_prefix).strip()
            body = []
        elif title and line.strip():
            body.append(line)
    if title and body:
        chunks.append(KnowledgeChunk(source=f"{source_prefix}: {title}", text="\n".join(body).strip()))
    return chunks


def _catalog_lines(path: Path) -> list[KnowledgeChunk]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    brand = ""
    chunks: list[KnowledgeChunk] = []
    for line in lines:
        if line.startswith("## "):
            brand = line.removeprefix("## ").strip()
        elif line.startswith("- **"):
            chunks.append(KnowledgeChunk(source=f"Каталог: {brand or 'автомобили'}", text=line.removeprefix("- ")))
    return chunks
