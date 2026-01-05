"""
Auto-generate games_index.json from PDF files using BoardGameGeek API.

Usage:
    uv run python scripts/generate_games_index.py

Prerequisites:
    1. Register your application at https://boardgamegeek.com/applications
    2. Add your BGG API token to .env file: BGG_API_TOKEN=your-token-here
"""
import json
import os
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


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

    try:
        response = requests.get(search_url, params=params, headers=headers, timeout=10)
        response.raise_for_status()

        root = ET.fromstring(response.content)
        items = root.findall("item")

        if not items:
            print(f"⚠️  '{game_name}' not found in BGG")
            return None

        # Take first result
        game_id = items[0].get("id")

        # Get game details
        # BGG API requires delay between requests
        time.sleep(1)

        details_url = "https://boardgamegeek.com/xmlapi2/thing"
        details_params = {"id": game_id, "type": "boardgame"}

        details_response = requests.get(details_url, params=details_params, headers=headers, timeout=10)
        details_response.raise_for_status()

        details_root = ET.fromstring(details_response.content)
        item = details_root.find("item")

        if item is None:
            return None

        # Extract names
        names = item.findall("name")
        primary_name = None
        alternate_names = []

        for name in names:
            name_type = name.get("type")
            name_value = name.get("value")

            if name_type == "primary":
                primary_name = name_value
            elif name_type == "alternate":
                alternate_names.append(name_value)

        # Extract categories/mechanics for tags
        categories = [cat.get("value") for cat in item.findall("link[@type='boardgamecategory']")]
        mechanics = [mech.get("value") for mech in item.findall("link[@type='boardgamemechanic']")]

        return {
            "bgg_id": game_id,
            "primary_name": primary_name,
            "alternate_names": alternate_names,
            "categories": categories[:5],  # First 5
            "mechanics": mechanics[:5]
        }

    except Exception as e:
        print(f"❌ Error searching '{game_name}': {e}")
        return None


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

    games_index = {"games": []}

    for pdf_file in sorted(pdf_files):
        # Skip expansions and FAQ files
        if " - " in pdf_file.stem:
            continue

        game_name = pdf_file.stem

        # Check if already in index
        if game_name in existing_games:
            print(f"✅ {game_name} (already in index)")
            games_index["games"].append(existing_games[game_name])
            continue

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

            # If no Russian names, add English name as fallback
            if not russian_names:
                russian_names = [game_name]

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
            # Fallback: create basic entry
            game_entry = {
                "english_name": game_name,
                "russian_names": [game_name],
                "pdf_files": related_pdfs,
                "tags": []
            }
            print(f"⚠️  {game_name} (BGG not found, created basic entry)")

        games_index["games"].append(game_entry)

    # Save index
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(games_index, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Index saved to {output_file}")
    print(f"📊 Total games: {len(games_index['games'])}")


if __name__ == "__main__":
    print("🎮 BoardGameGeek API games_index.json Generator\n")
    generate_index_from_pdfs()
