"""
Auto-fill games inventory CSV using BoardGameGeek API.

This script intelligently searches BGG for game names based on PDF filenames
and helps you fill the inventory CSV semi-automatically.

Usage:
    uv run python scripts/auto_fill_inventory.py [--auto-accept] [--max-results=3] [--similarity-threshold=0.8]

Flags:
    --auto-accept: Automatically accept first result (skip manual selection and similarity matching)
    --max-results: Number of search results to show (default: 3)
    --similarity-threshold: Minimum similarity score for auto-selection (default: 0.8, range: 0.0-1.0)
"""
import argparse
import csv
import difflib
import os
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


BGG_REQUEST_DELAY = 1  # seconds

def clean_filename_for_search(filename: str) -> str:
    """Clean PDF filename to create search query.

    Removes common patterns like:
    - File extensions (.pdf)
    - Edition markers (2nd edition, v2, etc.)
    - Language markers (RUS, EN, etc.)
    - Publisher names
    - Underscores, dashes

    Args:
        filename: PDF filename

    Returns:
        Cleaned search query
    """
    # Remove extension
    query = filename.replace('.pdf', '').replace('.PDF', '')

    # Remove common patterns
    patterns_to_remove = [
        r'\s*\(\d+\s*edition\)',  # (2nd edition)
        r'\s*\d+\s*ed\b',  # 2nd ed
        r'\s*v?\d+\.\d+',  # v2.0
        r'\s*\(RUS\)',  # (RUS)
        r'\s*\(EN\)',  # (EN)
        r'\s*\(Russian\)',  # (Russian)
        r'\s*\(English\)',  # (English)
        r'\s*-\s*правила',  # - правила
        r'\s*-\s*rules',  # - rules
        r'\s*правила$',  # правила at end
        r'\s*rules$',  # rules at end
    ]

    for pattern in patterns_to_remove:
        query = re.sub(pattern, '', query, flags=re.IGNORECASE)

    # Replace separators with spaces
    query = query.replace('_', ' ').replace('-', ' ')

    # Remove extra whitespace
    query = ' '.join(query.split())

    return query.strip()


def search_bgg_game(query: str, max_results: int = 3) -> list[dict]:
    """Search for games on BoardGameGeek.

    Args:
        query: Search query (game name)
        max_results: Maximum number of results to return

    Returns:
        List of game dictionaries with metadata
    """
    bgg_token = os.getenv("BGG_API_TOKEN", "").strip()

    if not bgg_token:
        print(f"❌ No BGG_API_TOKEN found in .env file")
        return []

    # BGG XML API v2 search
    search_url = "https://boardgamegeek.com/xmlapi2/search"
    params = {
        "query": query,
        "type": "boardgame"
    }

    headers = {
        "User-Agent": "RulesLawyerBot/1.0 (https://github.com/RomanShnurov/RulesLawyerBot)",
        "Authorization": f"Bearer {bgg_token}"
    }

    try:
        response = requests.get(search_url, params=params, headers=headers, timeout=10)
        response.raise_for_status()

        # Delay after search request (BGG API recommends max 2 requests/second)
        time.sleep(BGG_REQUEST_DELAY)

        root = ET.fromstring(response.content)
        items = root.findall("item")

        if not items:
            return []

        # Get details for top results
        results = []
        for i, item in enumerate(items[:max_results]):
            game_id = item.get("id")
            game_name = item.find("name").get("value")
            year = item.find("yearpublished")
            year_published = year.get("value") if year is not None else "Unknown"

            # Get full details
            details = get_game_details(game_id, headers)
            if details:
                details["year_published"] = year_published
                results.append(details)
            else:
                # Fallback if details fetch fails
                results.append({
                    "bgg_id": game_id,
                    "primary_name": game_name,
                    "year_published": year_published,
                    "alternate_names": [],
                    "categories": [],
                    "mechanics": []
                })

            # Delay after each details request, except the last one
            if i < len(items[:max_results]) - 1:
                time.sleep(BGG_REQUEST_DELAY)

        return results

    except Exception as e:
        print(f"❌ Error searching BGG: {e}")
        return []


def get_game_details(game_id: str, headers: dict) -> Optional[dict]:
    """Fetch detailed game information from BGG.

    Args:
        game_id: BGG game ID
        headers: HTTP headers for API request

    Returns:
        Dictionary with game details or None
    """
    details_url = "https://boardgamegeek.com/xmlapi2/thing"
    params = {"id": game_id, "type": "boardgame"}

    try:
        response = requests.get(details_url, params=params, headers=headers, timeout=10)
        response.raise_for_status()

        root = ET.fromstring(response.content)
        item = root.find("item")

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

        # Extract categories and mechanics
        categories = [cat.get("value") for cat in item.findall("link[@type='boardgamecategory']")]
        mechanics = [mech.get("value") for mech in item.findall("link[@type='boardgamemechanic']")]

        return {
            "bgg_id": game_id,
            "primary_name": primary_name,
            "alternate_names": alternate_names,
            "categories": categories[:5],
            "mechanics": mechanics[:5]
        }

    except Exception as e:
        print(f"  Warning: Could not fetch details for game {game_id}: {e}")
        return None


def calculate_similarity(str1: str, str2: str) -> float:
    """Calculate similarity between two strings.

    Uses SequenceMatcher to compute similarity ratio (0.0 to 1.0).

    Args:
        str1: First string (usually query/filename)
        str2: Second string (usually BGG game name)

    Returns:
        Similarity score from 0.0 (no match) to 1.0 (exact match)
    """
    # Normalize strings for comparison
    s1 = str1.lower().strip()
    s2 = str2.lower().strip()

    return difflib.SequenceMatcher(None, s1, s2).ratio()


def find_best_match(
    results: list[dict],
    query: str,
    threshold: float = 0.8
) -> tuple[Optional[dict], float, list[tuple[dict, float]]]:
    """Find best matching game from BGG results based on similarity.

    Calculates similarity between query and each result's primary name
    and alternate names. Returns the best match if it exceeds threshold.

    Args:
        results: List of game results from BGG
        query: Original search query (cleaned filename)
        threshold: Minimum similarity score for auto-selection

    Returns:
        Tuple of (best_match, best_score, all_scored_results)
        - best_match: Game dictionary if score >= threshold, else None
        - best_score: Highest similarity score found
        - all_scored_results: List of (game, score) tuples sorted by score
    """
    if not results:
        return None, 0.0, []

    scored_results = []

    for game in results:
        # Calculate similarity with primary name
        primary_similarity = calculate_similarity(query, game['primary_name'])

        # Also check alternate names for better matching
        max_similarity = primary_similarity
        for alt_name in game.get('alternate_names', []):
            alt_similarity = calculate_similarity(query, alt_name)
            max_similarity = max(max_similarity, alt_similarity)

        scored_results.append((game, max_similarity))

    # Sort by similarity (highest first)
    scored_results.sort(key=lambda x: x[1], reverse=True)

    best_game, best_score = scored_results[0]

    # Return best match only if it meets threshold
    if best_score >= threshold:
        return best_game, best_score, scored_results
    else:
        return None, best_score, scored_results


def interactive_selection(
    scored_results: list[tuple[dict, float]],
    filename: str,
    query: str
) -> Optional[dict]:
    """Let user select the correct game from search results.

    Args:
        scored_results: List of (game, similarity_score) tuples sorted by score
        filename: Original PDF filename
        query: Cleaned search query

    Returns:
        Selected game dictionary or None
    """
    if not scored_results:
        return None

    print(f"\n📄 File: {filename}")
    print(f"🔍 Query: '{query}'")
    print(f"Found {len(scored_results)} results on BGG (sorted by similarity):\n")

    for i, (game, similarity) in enumerate(scored_results, 1):
        # Color code based on similarity
        if similarity >= 0.8:
            icon = "🟢"
        elif similarity >= 0.6:
            icon = "🟡"
        else:
            icon = "🔴"

        print(f"{i}. {icon} {game['primary_name']} ({game['year_published']}) - {similarity:.0%} match")

        # Show Russian names if available
        russian_names = [
            name for name in game.get('alternate_names', [])
            if any('\u0400' <= c <= '\u04FF' for c in name)
        ]
        if russian_names:
            print(f"   Russian: {', '.join(russian_names[:3])}")

        # Show categories
        if game.get('categories'):
            print(f"   Tags: {', '.join(game['categories'][:3])}")

    print(f"\n0. Skip (I'll fill manually)")
    print(f"s. Search with different query")

    while True:
        choice = input(f"\nSelect game [1-{len(scored_results)}/0/s]: ").strip().lower()

        if choice == '0':
            return None
        elif choice == 's':
            new_query = input("Enter search query: ").strip()
            if new_query:
                new_results = search_bgg_game(new_query)
                if new_results:
                    # Re-score with new query
                    _, _, new_scored = find_best_match(new_results, new_query, threshold=0.0)
                    return interactive_selection(new_scored, filename, new_query)
                else:
                    print("❌ No results found")
                    return None
            else:
                return None
        elif choice.isdigit() and 1 <= int(choice) <= len(scored_results):
            return scored_results[int(choice) - 1][0]  # Return game, not tuple
        else:
            print(f"❌ Invalid choice. Enter 1-{len(scored_results)}, 0, or s")


def save_csv(csv_path: Path, rows: list[dict], fieldnames: list[str]):
    """Save CSV data to file with explicit flush.

    This ensures data is written to disk immediately, preventing data loss
    if the script crashes or is interrupted.

    Args:
        csv_path: Path to CSV file
        rows: List of row dictionaries
        fieldnames: CSV column names
    """
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        f.flush()  # Ensure data is written to disk
        # Note: On Windows, this might not guarantee disk write
        # For absolute guarantee, could use os.fsync(f.fileno())


def auto_fill_inventory(
    csv_path: Path,
    auto_accept: bool = False,
    max_results: int = 3,
    similarity_threshold: float = 0.8
):
    """Auto-fill inventory CSV with BGG data.

    Args:
        csv_path: Path to inventory CSV file
        auto_accept: Automatically accept first result (skip similarity matching)
        max_results: Number of search results to show
        similarity_threshold: Minimum similarity for auto-selection (0.0-1.0)
    """
    if not csv_path.exists():
        print(f"❌ CSV file not found: {csv_path}")
        print(f"   Run scripts/analyze_pdfs.py first")
        return

    # Read existing CSV
    with open(csv_path, encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames

    if not rows:
        print("⚠️  CSV file is empty")
        return

    print(f"🎮 Auto-fill Inventory with BGG API")
    print(f"{'=' * 60}\n")
    print(f"📊 Loaded {len(rows)} entries from CSV")

    if auto_accept:
        print(f"Mode: Auto-accept first result (similarity matching disabled)")
    else:
        print(f"Mode: Smart matching (auto-select if similarity >= {similarity_threshold:.0%})")

    print()

    updated_count = 0
    skipped_count = 0
    auto_matched_count = 0
    already_filled_count = 0

    try:
        for i, row in enumerate(rows, 1):
            filename = row['current_filename']

            # Skip if already filled
            if row.get('english_name', '').strip():
                print(f"[{i}/{len(rows)}] ⏭️  {filename} (already filled, skipping)")
                already_filled_count += 1
                continue

            # Clean filename for search
            query = clean_filename_for_search(filename)

            if not query:
                print(f"[{i}/{len(rows)}] ⏭️  {filename} (couldn't extract query)")
                skipped_count += 1
                continue

            print(f"\n[{i}/{len(rows)}] 🔎 Searching for: '{query}'")

            # Search BGG
            results = search_bgg_game(query, max_results=max_results)

            if not results:
                print(f"   ❌ No results found on BGG")
                skipped_count += 1
                continue

            # Select game based on mode
            selected = None

            if auto_accept:
                # Auto-accept mode: just take first result
                selected = results[0]
                print(f"   ✅ Auto-selected: {selected['primary_name']} ({selected['year_published']})")
            else:
                # Smart matching mode: try to find best match based on similarity
                best_match, best_score, scored_results = find_best_match(
                    results, query, threshold=similarity_threshold
                )

                if best_match:
                    # Found good match automatically
                    selected = best_match
                    print(f"   🎯 Auto-matched: {selected['primary_name']} ({selected['year_published']}) - {best_score:.0%} similarity")
                    auto_matched_count += 1
                else:
                    # Similarity too low, ask user
                    print(f"   ⚠️  Best match: {scored_results[0][0]['primary_name']} - {scored_results[0][1]:.0%} similarity (below {similarity_threshold:.0%} threshold)")
                    print(f"   👤 Manual selection required")
                    selected = interactive_selection(scored_results, filename, query)

            if not selected:
                print(f"   ⏭️  Skipped")
                skipped_count += 1
                continue

            # Extract Russian names
            russian_names = [
                name for name in selected.get('alternate_names', [])
                if any('\u0400' <= c <= '\u04FF' for c in name)
            ]

            # Update row with BGG data
            row['english_name'] = selected['primary_name']  # English name from BGG
            row['russian_names'] = ', '.join(russian_names[:5]) if russian_names else selected['primary_name']
            # Note: pdf_title stays as-is (from PDF metadata), we don't overwrite it
            row['notes'] = f"BGG ID: {selected['bgg_id']}"

            # Auto-detect if it's an expansion (heuristic)
            if any(keyword in selected['primary_name'].lower() for keyword in ['expansion', 'extension', 'дополнение']):
                row['is_expansion'] = 'yes'

            print(f"   ✅ Updated: {selected['primary_name']}")
            if russian_names:
                print(f"      Russian: {', '.join(russian_names[:3])}")

            updated_count += 1

            # Save CSV after each update (to preserve progress if script crashes)
            save_csv(csv_path, rows, fieldnames)
            print(f"   💾 Progress saved")

    except KeyboardInterrupt:
        print(f"\n\n⚠️  Process interrupted by user (Ctrl+C)")
        print(f"📊 Progress before interruption:")
        print(f"   ✅ Updated: {updated_count}")
        if auto_matched_count > 0:
            print(f"   🎯 Auto-matched: {auto_matched_count}")
        print(f"   ⏭️  Already filled: {already_filled_count}")
        print(f"   ⏭️  Skipped: {skipped_count}")
        print(f"\n💾 All progress has been saved to: {csv_path}")
        print(f"✅ You can safely re-run the script to continue from where you left off")
        return

    print(f"\n{'=' * 60}")
    print(f"📊 Statistics:")
    print(f"   ✅ Updated: {updated_count}")
    if auto_matched_count > 0:
        print(f"   🎯 Auto-matched: {auto_matched_count}")
    print(f"   ⏭️  Already filled: {already_filled_count}")
    print(f"   ⏭️  Skipped: {skipped_count}")
    print(f"\n💾 CSV saved: {csv_path}")
    print(f"\nNext steps:")
    print(f"1. Review CSV (check english_name, is_expansion columns)")
    print(f"2. Run: uv run python scripts/rename_pdfs.py --dry-run")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Auto-fill inventory CSV using BoardGameGeek API with smart similarity matching"
    )
    parser.add_argument(
        '--auto-accept',
        action='store_true',
        help='Automatically accept first search result (skip similarity matching and manual selection)'
    )
    parser.add_argument(
        '--max-results',
        type=int,
        default=3,
        help='Number of search results to show (default: 3)'
    )
    parser.add_argument(
        '--similarity-threshold',
        type=float,
        default=0.8,
        help='Minimum similarity score for auto-selection, 0.0-1.0 (default: 0.8 = 80%%)'
    )
    parser.add_argument(
        '--csv',
        type=str,
        default='rules_pdfs_inventory.csv',
        help='Path to inventory CSV file (default: rules_pdfs_inventory.csv)'
    )

    args = parser.parse_args()

    # Validate similarity threshold
    if not 0.0 <= args.similarity_threshold <= 1.0:
        print(f"❌ Error: --similarity-threshold must be between 0.0 and 1.0")
        exit(1)

    csv_path = Path(args.csv)
    auto_fill_inventory(
        csv_path,
        auto_accept=args.auto_accept,
        max_results=args.max_results,
        similarity_threshold=args.similarity_threshold
    )
