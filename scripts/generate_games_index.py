"""
Auto-generate games_index.json from PDF files using BoardGameGeek API.

Usage:
    uv run python scripts/generate_games_index.py

Prerequisites:
    1. Register your application at https://boardgamegeek.com/applications
    2. Add your BGG API token to .env file: BGG_API_TOKEN=your-token-here
"""
import csv
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

CSV_PATH = Path("rules_pdfs_inventory.csv")


def _stem_key(name: str) -> str:
    """Normalize a name to match how rename_pdfs.py builds the PDF stem.
    Keeps load_csv_metadata in sync with sanitize_for_windows without import cycles."""
    for bad, good in (
        (":", " -"), ("/", "-"), ("\\", "-"), ("|", "-"),
        ("?", ""), ("*", ""), ('"', "'"), ("<", "("), (">", ")"),
    ):
        name = name.replace(bad, good)
    return re.sub(r"\s+", " ", name).strip(" .")


def load_csv_metadata() -> dict[str, dict]:
    """Load PDF-stem-key -> {bgg_id, russian_names} from inventory CSV."""
    meta: dict[str, dict] = {}
    if not CSV_PATH.exists():
        return meta
    with open(CSV_PATH, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            en = (row.get("english_name") or "").strip()
            if not en:
                continue
            key = _stem_key(en)
            entry = meta.setdefault(key, {"bgg_id": None, "russian_names": []})
            if entry["bgg_id"] is None:
                m = re.search(r"BGG ID:\s*(\d+)", row.get("notes", "") or "")
                if m:
                    entry["bgg_id"] = m.group(1)
            ru = (row.get("russian_names") or "").strip()
            if ru and ru not in entry["russian_names"]:
                entry["russian_names"].append(ru)
    return meta


def _bgg_request(url: str, params: dict, headers: dict, *, max_retries: int = 5) -> Optional[bytes]:
    """GET with exponential backoff on 429/5xx. Returns response content or None."""
    delay = 2
    for attempt in range(max_retries):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=15)
            if r.status_code == 429 or r.status_code >= 500:
                print(f"   ⏳ HTTP {r.status_code}, retry in {delay}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(delay)
                delay = min(delay * 2, 30)
                continue
            r.raise_for_status()
            return r.content
        except requests.RequestException as e:
            print(f"   ⏳ {e}, retry in {delay}s (attempt {attempt + 1}/{max_retries})")
            time.sleep(delay)
            delay = min(delay * 2, 30)
    return None


def fetch_bgg_details(bgg_id: str, headers: dict) -> Optional[dict]:
    """Fetch game details by known BGG ID. Skips the search step."""
    details_url = "https://boardgamegeek.com/xmlapi2/thing"
    content = _bgg_request(details_url, {"id": bgg_id, "type": "boardgame"}, headers)
    if content is None:
        return None
    try:
        details_root = ET.fromstring(content)
    except ET.ParseError:
        return None
    item = details_root.find("item")
    if item is None:
        return None

    primary_name = None
    alternate_names = []
    for name in item.findall("name"):
        name_type = name.get("type")
        name_value = name.get("value")
        if name_type == "primary":
            primary_name = name_value
        elif name_type == "alternate":
            alternate_names.append(name_value)

    categories = [cat.get("value") for cat in item.findall("link[@type='boardgamecategory']")]
    mechanics = [mech.get("value") for mech in item.findall("link[@type='boardgamemechanic']")]

    return {
        "bgg_id": bgg_id,
        "primary_name": primary_name,
        "alternate_names": alternate_names,
        "categories": categories[:5],
        "mechanics": mechanics[:5],
    }


def search_bgg_game(game_name: str) -> Optional[dict]:
    """
    Search for a game in BoardGameGeek API.

    Args:
        game_name: Game name in English

    Returns:
        Dictionary with game information or None
    """
    # Get BGG API token from environment
    bgg_token = os.getenv("BGG_API_TOKEN", "").strip()

    if not bgg_token:
        print(f"⚠️  No BGG_API_TOKEN found in .env file")
        print(f"   Register at https://boardgamegeek.com/applications")
        return None

    # BGG XML API v2
    search_url = "https://boardgamegeek.com/xmlapi2/search"
    params = {
        "query": game_name,
        "type": "boardgame",
        "exact": 1  # Exact match
    }

    headers = {
        "User-Agent": "RulesLawyerBot/1.0 (https://github.com/RomanShnurov/RulesLawyerBot)",
        "Authorization": f"Bearer {bgg_token}"
    }

    content = _bgg_request(search_url, params, headers)
    if content is None:
        return None
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return None
    items = root.findall("item")
    if not items:
        print(f"⚠️  '{game_name}' not found in BGG")
        return None

    game_id = items[0].get("id")
    time.sleep(1)
    return fetch_bgg_details(game_id, headers)


def generate_index_from_pdfs():
    """Generate games_index.json from PDF files in rules_pdfs/"""

    pdf_dir = Path("rules_pdfs")
    output_file = pdf_dir / "games_index.json"

    # Load existing index
    existing_games = {}
    if output_file.exists():
        with open(output_file, encoding="utf-8") as f:
            existing_data = json.load(f)
            existing_games = {
                game["english_name"]: game
                for game in existing_data.get("games", [])
            }
            print(f"📖 Loaded existing index: {len(existing_games)} games")

    # Find all PDF files
    pdf_files = list(pdf_dir.glob("*.pdf"))

    if not pdf_files:
        print("❌ No PDF files found in rules_pdfs/")
        return

    print(f"\n🔍 Found {len(pdf_files)} PDF files")

    csv_meta = load_csv_metadata()
    print(f"📋 Loaded BGG IDs from CSV: {sum(1 for v in csv_meta.values() if v['bgg_id'])} entries")

    bgg_token = os.getenv("BGG_API_TOKEN", "").strip()
    headers = {
        "User-Agent": "RulesLawyerBot/1.0 (https://github.com/RomanShnurov/RulesLawyerBot)",
    }
    if bgg_token:
        headers["Authorization"] = f"Bearer {bgg_token}"

    games_index = {"games": []}

    for pdf_file in sorted(pdf_files):
        # Skip expansions and FAQ files
        if " - " in pdf_file.stem:
            continue

        game_name = pdf_file.stem

        # Reuse existing entry only if it has bgg_id (otherwise re-fetch)
        existing = existing_games.get(game_name)
        if existing and existing.get("bgg_id"):
            print(f"✅ {game_name} (already in index)")
            games_index["games"].append(existing)
            continue

        # Prefer cached BGG ID from CSV — skip search step
        meta = csv_meta.get(game_name, {})
        cached_id = meta.get("bgg_id")
        if cached_id:
            print(f"\n🎯 Fetching BGG details for '{game_name}' (ID {cached_id})...")
            bgg_info = fetch_bgg_details(cached_id, headers)
            time.sleep(1)
        else:
            print(f"\n🔎 Searching BGG for '{game_name}'...")
            bgg_info = search_bgg_game(game_name)

        # Find all related PDF files
        related_pdfs = [
            f.name for f in pdf_dir.glob("*.pdf")
            if f.stem.startswith(game_name)
        ]

        if bgg_info:
            # Filter Russian names from alternate_names (Cyrillic check)
            russian_names = [
                name for name in bgg_info["alternate_names"]
                if any('\u0400' <= c <= '\u04FF' for c in name)
            ]

            # Fallback chain: BGG -> CSV -> English name
            if not russian_names:
                russian_names = meta.get("russian_names") or [game_name]

            game_entry = {
                "english_name": game_name,
                "russian_names": russian_names[:5],  # First 5 Russian variants
                "pdf_files": related_pdfs,
                "tags": (bgg_info["categories"] + bgg_info["mechanics"])[:5],
                "bgg_id": bgg_info["bgg_id"]
            }

            print(f"✅ {game_name}")
            print(f"   Russian names: {', '.join(russian_names[:3])}")

        else:
            # Fallback: use CSV metadata when BGG unreachable
            game_entry = {
                "english_name": game_name,
                "russian_names": meta.get("russian_names") or [game_name],
                "pdf_files": related_pdfs,
                "tags": [],
            }
            if cached_id:
                game_entry["bgg_id"] = cached_id
            print(f"⚠️  {game_name} (BGG fetch failed, used CSV data)")

        games_index["games"].append(game_entry)

    # Save index
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(games_index, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Index saved to {output_file}")
    print(f"📊 Total games: {len(games_index['games'])}")


if __name__ == "__main__":
    print("🎮 BoardGameGeek API games_index.json Generator")
    print("   Powered by BoardGameGeek (https://boardgamegeek.com)\n")
    generate_index_from_pdfs()
    print("\n" + "=" * 60)
    print("Game metadata powered by BoardGameGeek")
    print("https://boardgamegeek.com")
    print("=" * 60)
