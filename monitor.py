from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Iterable

import requests
from bs4 import BeautifulSoup

SOURCE_URL = "https://cp.toyota.jp/rentacar/"
STATE_PATH = Path("state.json")

PERIOD_RE = re.compile(
    r"\d{4}年\s*\d{1,2}月\s*\d{1,2}日\s*[～〜~-]\s*(?:\d{4}年\s*)?\d{1,2}月\s*\d{1,2}日"
)
PHONE_RE = re.compile(r"0\d{1,4}-\d{1,4}-\d{3,4}")


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def find_label(tokens: list[str], start: int, labels: set[str], limit: int = 20) -> int | None:
    end = min(len(tokens), start + limit)
    for i in range(start, end):
        if compact(tokens[i]) in labels:
            return i
    return None


def find_matching(tokens: list[str], start: int, pattern: re.Pattern[str], limit: int = 20) -> int | None:
    end = min(len(tokens), start + limit)
    for i in range(start, end):
        if pattern.search(tokens[i]):
            return i
    return None


def listing_id(item: dict[str, str]) -> str:
    # 車種にはナンバーが入ることが多いので、同じ経路でも別車両を区別できます。
    stable = "\n".join(
        [item["start"], item["return"], item["period"], item["car"]]
    )
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()[:24]


def extract_listings(html: bytes) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()

    tokens = [clean(x) for x in soup.stripped_strings if clean(x)]
    results: list[dict[str, str]] = []
    seen_ids: set[str] = set()

    i = 0
    while i < len(tokens):
        token = compact(tokens[i])
        if token == "出発":
            if i + 1 >= len(tokens) or compact(tokens[i + 1]) != "店舗":
                i += 1
                continue
            start_pos = i + 2
        elif token == "出発店舗":
            start_pos = i + 1
        else:
            i += 1
            continue

        return_label = find_label(tokens, start_pos, {"返却", "返却店舗"}, limit=15)
        if return_label is None or return_label == start_pos:
            i += 1
            continue

        start_store = clean(" ".join(tokens[start_pos:return_label]))
        return_pos = return_label + 1
        if compact(tokens[return_label]) == "返却":
            if return_pos < len(tokens) and compact(tokens[return_pos]) == "店舗":
                return_pos += 1

        period_label = find_label(tokens, return_pos, {"出発期間"}, limit=15)
        if period_label is None or period_label == return_pos:
            i += 1
            continue

        return_store = clean(" ".join(tokens[return_pos:period_label]))
        period_idx = find_matching(tokens, period_label + 1, PERIOD_RE, limit=8)
        if period_idx is None:
            i += 1
            continue
        period_match = PERIOD_RE.search(tokens[period_idx])
        assert period_match is not None
        period = clean(period_match.group(0))

        car_label = find_label(tokens, period_idx + 1, {"車種"}, limit=20)
        if car_label is None:
            i += 1
            continue
        condition_label = find_label(tokens, car_label + 1, {"車両条件"}, limit=12)
        if condition_label is None or condition_label == car_label + 1:
            i += 1
            continue

        car = clean(" ".join(tokens[car_label + 1:condition_label]))

        phone_label = find_label(tokens, condition_label + 1, {"予約電話番号"}, limit=20)
        if phone_label is None:
            i += 1
            continue

        condition_parts = []
        for x in tokens[condition_label + 1:phone_label]:
            if PERIOD_RE.search(x):
                continue
            condition_parts.append(x)
        conditions = clean(" ".join(condition_parts))

        phone_idx = find_matching(tokens, phone_label + 1, PHONE_RE, limit=10)
        if phone_idx is None:
            i += 1
            continue
        phone_match = PHONE_RE.search(tokens[phone_idx])
        assert phone_match is not None
        phone = phone_match.group(0)
        contact = clean(" ".join(tokens[phone_label + 1:phone_idx]))

        if not all([start_store, return_store, period, car, phone]):
            i += 1
            continue

        item = {
            "start": start_store,
            "return": return_store,
            "period": period,
            "car": car,
            "conditions": conditions or "記載なし",
            "contact": contact or "記載なし",
            "phone": phone,
        }
        item["id"] = listing_id(item)

        if item["id"] not in seen_ids:
            seen_ids.add(item["id"])
            results.append(item)

        i = phone_idx + 1

    return results


def parse_keywords(name: str) -> list[str]:
    raw = os.getenv(name, "").strip()
    return [x.strip() for x in raw.split(",") if x.strip()]


def includes_any(text: str, keywords: Iterable[str]) -> bool:
    words = list(keywords)
    if not words:
        return True
    folded = text.casefold()
    return any(word.casefold() in folded for word in words)


def apply_filters(items: list[dict[str, str]]) -> list[dict[str, str]]:
    start_words = parse_keywords("FILTER_START")
    return_words = parse_keywords("FILTER_RETURN")
    car_words = parse_keywords("FILTER_CAR")

    return [
        item
        for item in items
        if includes_any(item["start"], start_words)
        and includes_any(item["return"], return_words)
        and includes_any(item["car"], car_words)
    ]


def fetch_page() -> bytes:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; KatamichiGoMonitor/1.0; "
            "+https://github.com/)"
        )
    }
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.get(SOURCE_URL, headers=headers, timeout=30)
            response.raise_for_status()
            return response.content
        except requests.RequestException as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2 ** attempt)
    assert last_error is not None
    raise last_error


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"initialized": False, "current_ids": []}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("state.json must contain an object")
        return data
    except (json.JSONDecodeError, OSError, ValueError):
        return {"initialized": False, "current_ids": []}


def save_state(items: list[dict[str, str]]) -> None:
    data = {
        "initialized": True,
        "current_ids": [item["id"] for item in items],
    }
    STATE_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def send_discord(payload: dict) -> None:
    webhook = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook:
        raise RuntimeError("DISCORD_WEBHOOK_URL is not set")

    response = requests.post(webhook, json=payload, timeout=30)
    if response.status_code == 429:
        try:
            retry_after = float(response.json().get("retry_after", 1))
        except Exception:
            retry_after = 1
        time.sleep(min(retry_after, 10))
        response = requests.post(webhook, json=payload, timeout=30)
    response.raise_for_status()


def notify_started(count: int) -> None:
    send_discord(
        {
            "content": (
                "✅ **トヨタ 片道GO! の監視を開始しました**\n"
                f"現在の条件に一致する掲載: **{count}件**\n"
                "次回以降、新しく追加された掲載だけ通知します。"
            )
        }
    )


def notify_listing(item: dict[str, str]) -> None:
    embed = {
        "title": "🚗 片道GO! 新着",
        "url": SOURCE_URL,
        "description": f"**{item['start']}**\n➡️ **{item['return']}**",
        "fields": [
            {"name": "車種", "value": item["car"][:1024], "inline": False},
            {"name": "出発期間", "value": item["period"][:1024], "inline": False},
            {"name": "車両条件", "value": item["conditions"][:1024], "inline": False},
            {
                "name": "予約電話番号",
                "value": f"{item['contact']}\n**{item['phone']}**"[:1024],
                "inline": False,
            },
        ],
        "footer": {"text": "トヨタ 片道GO! 自動監視"},
    }
    send_discord({"embeds": [embed]})


def main() -> None:
    html = fetch_page()
    all_items = extract_listings(html)
    if not all_items:
        raise RuntimeError(
            "片道GO! の掲載を1件も解析できませんでした。ページ構造が変わった可能性があります。"
        )

    items = apply_filters(all_items)
    state = load_state()
    old_ids = set(state.get("current_ids", []))
    current_ids = {item["id"] for item in items}

    if not state.get("initialized", False):
        notify_started(len(items))
        save_state(items)
        print(f"Initialized with {len(items)} matching listings ({len(all_items)} total).")
        return

    new_items = [item for item in items if item["id"] not in old_ids]
    print(
        f"Found {len(all_items)} total, {len(items)} matching, "
        f"{len(new_items)} new listing(s)."
    )

    for item in new_items:
        notify_listing(item)
        time.sleep(0.4)

    # 現在掲載中のIDだけ保存するため、一度消えた案件が再掲載された場合も通知できます。
    if current_ids != old_ids:
        save_state(items)


if __name__ == "__main__":
    main()
