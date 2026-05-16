"""
Fill missing english_name, russian_names, and BGG ID in rules_pdfs_inventory.csv
by searching BoardGameGeek XML API v2.

Key improvements over generate_games_index.py:
- Searches by cleaned pdf_title (Russian name), not by filename
- Uses fuzzy search (no exact=1)
- Falls back to filename-based search if pdf_title doesn't work
- Updates CSV directly

Usage:
    uv run python scripts/fill_inventory_from_bgg.py
    uv run python scripts/fill_inventory_from_bgg.py --dry-run
"""

import csv
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

BGG_SEARCH_URL = "https://boardgamegeek.com/xmlapi2/search"
BGG_THING_URL = "https://boardgamegeek.com/xmlapi2/thing"

bgg_token = os.getenv("BGG_API_TOKEN", "").strip()
if not bgg_token:
    print("ERROR: BGG_API_TOKEN not found in .env")
    sys.exit(1)

HEADERS = {
    "User-Agent": "RulesLawyerBot/1.0",
    "Authorization": f"Bearer {bgg_token}",
}
REQUEST_DELAY = 1.5  # seconds between requests

CSV_PATH = Path("rules_pdfs_inventory.csv")


def clean_pdf_title(pdf_title: str) -> str | None:
    """Extract clean game name from pdf_title."""
    name = pdf_title.strip()

    if not name or name.endswith(".indd") or name.endswith(".pdf") or len(name) < 3:
        return None

    # Remove various "rules" suffixes (Russian and English)
    patterns = [
        r"\s*[—–\-]\s*[Пп]равила\b.*$",
        r"\.\s*[Пп]равила\b.*$",
        r"\s+[Пп]равила\b.*$",
        r"\s*[—–\-]\s*правила\b.*$",
        r"\s+правила\b.*$",
        r"\s*\([Рр]ус\).*$",
        r"\s*\(rus\).*$",
        r"\s*[Rr]ulebook.*$",
        r"\s*[Rr]ules.*$",
        r"\s*[—–\-]\s*[Rr]ules.*$",
    ]

    for pattern in patterns:
        name = re.sub(pattern, "", name).strip()

    # Remove trailing punctuation
    name = name.rstrip(" .—–-:")

    return name if len(name) >= 2 else None


def clean_filename(filename: str) -> str | None:
    """Extract a searchable name from filename."""
    stem = Path(filename).stem

    # Remove common suffixes
    stem = re.sub(
        r"[-_]?(rulebook|rules|pravila|rus|eng|web|compressed|mini|low|res)",
        "",
        stem,
        flags=re.IGNORECASE,
    )
    # Remove hash suffixes like _kgzLCCH, _aXLFEfZ
    stem = re.sub(r"[_\s][A-Za-z0-9]{7}$", "", stem)
    # Remove trailing numbers/versions like _1, _2, (1), (2)
    stem = re.sub(r"[_\s]?\(\d+\)$", "", stem)
    stem = re.sub(r"[_\s]?\d+$", "", stem)

    # Replace separators with spaces
    stem = stem.replace("-", " ").replace("_", " ").strip()

    # Remove extra spaces
    stem = re.sub(r"\s+", " ", stem)

    return stem if len(stem) >= 2 else None


def normalize(text: str) -> set[str]:
    """Normalize text to a set of lowercase words for comparison."""
    text = re.sub(r"[^\w\s]", " ", text.lower())
    return {w for w in text.split() if len(w) >= 2}


def name_match_score(query: str, candidate_names: list[str]) -> float:
    """Score how well the query matches any of the candidate names.
    Returns 0.0 to 1.0 (1.0 = perfect match)."""
    query_words = normalize(query)
    if not query_words:
        return 0.0

    best_score = 0.0
    for name in candidate_names:
        name_words = normalize(name)
        if not name_words:
            continue
        # Use the shorter set for comparison
        smaller = min(query_words, name_words, key=len)
        larger = max(query_words, name_words, key=len)
        if not smaller:
            continue
        overlap = len(smaller & larger)
        score = overlap / len(smaller)
        best_score = max(best_score, score)

    return best_score


MATCH_THRESHOLD = 0.5  # At least 50% word overlap required


def search_bgg(query: str) -> list[dict]:
    """Search BGG for a game. Returns list of matches."""
    params = {"query": query, "type": "boardgame,boardgameexpansion"}

    try:
        resp = requests.get(
            BGG_SEARCH_URL, params=params, headers=HEADERS, timeout=15
        )
        resp.raise_for_status()

        root = ET.fromstring(resp.content)
        results = []

        for item in root.findall("item")[:10]:
            game_id = item.get("id")
            name_elem = item.find("name")
            name = name_elem.get("value") if name_elem is not None else ""
            year_elem = item.find("yearpublished")
            year = year_elem.get("value") if year_elem is not None else ""
            results.append({"id": game_id, "name": name, "year": year})

        return results
    except Exception as e:
        print(f"    ERROR searching BGG: {e}")
        return []


def get_bgg_details(game_id: str) -> dict | None:
    """Get game details from BGG by ID."""
    params = {"id": game_id, "type": "boardgame,boardgameexpansion"}

    try:
        resp = requests.get(BGG_THING_URL, params=params, headers=HEADERS, timeout=15)
        resp.raise_for_status()

        root = ET.fromstring(resp.content)
        item = root.find("item")

        if item is None:
            return None

        is_expansion = item.get("type") == "boardgameexpansion"

        names = item.findall("name")
        primary_name = ""
        russian_names = []

        for name in names:
            value = name.get("value", "")
            if name.get("type") == "primary":
                primary_name = value
            elif any("\u0400" <= c <= "\u04FF" for c in value):
                russian_names.append(value)

        return {
            "bgg_id": game_id,
            "primary_name": primary_name,
            "russian_names": russian_names,
            "is_expansion": is_expansion,
        }
    except Exception as e:
        print(f"    ERROR getting details: {e}")
        return None


def read_csv() -> tuple[list[str], list[dict]]:
    """Read CSV, return (fieldnames, rows). Strips whitespace from keys and values."""
    with open(CSV_PATH, encoding="utf-8") as f:
        reader = csv.DictReader(f, skipinitialspace=True)
        raw_fieldnames = reader.fieldnames or []
        # Strip whitespace from field names
        fieldnames = [fn.strip() for fn in raw_fieldnames]

        rows = []
        for raw_row in reader:
            row = {}
            for raw_key, value in raw_row.items():
                key = raw_key.strip()
                row[key] = value.strip() if value else ""
            rows.append(row)

    return fieldnames, rows


def write_csv(fieldnames: list[str], rows: list[dict]):
    """Write rows back to CSV."""
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _find_best_match(
    query: str,
    search_results: list[dict],
    fallback_query: str | None = None,
) -> dict | None:
    """Find the best matching result by validating names against query.

    For each search result, fetches details and checks if the primary name
    or any alternate name matches the query well enough.
    Returns the details dict or None.
    """
    for candidate in search_results[:5]:  # Check top 5 results
        # Quick check: does the search result name match the query?
        search_score = name_match_score(query, [candidate["name"]])
        if search_score < MATCH_THRESHOLD and fallback_query:
            search_score = name_match_score(fallback_query, [candidate["name"]])

        if search_score >= MATCH_THRESHOLD:
            print(
                f"    Found: {candidate['name']} ({candidate['year']}) "
                f"[ID: {candidate['id']}] (score: {search_score:.2f})"
            )
            time.sleep(REQUEST_DELAY)
            details = get_bgg_details(candidate["id"])
            if details:
                # Double-check: verify with all names (primary + russian)
                all_names = [details["primary_name"]] + details["russian_names"]
                final_score = name_match_score(query, all_names)
                if fallback_query:
                    final_score = max(
                        final_score, name_match_score(fallback_query, all_names)
                    )
                if final_score >= MATCH_THRESHOLD:
                    return details
                else:
                    print(
                        f"    REJECTED after details check "
                        f"(score: {final_score:.2f} < {MATCH_THRESHOLD})"
                    )
        # If first candidate doesn't match, try next silently

    # No good match found among top results
    return None


def main():
    dry_run = "--dry-run" in sys.argv

    if dry_run:
        print("=== DRY RUN (no changes will be saved) ===\n")

    fieldnames, rows = read_csv()
    print(f"Loaded {len(rows)} rows")
    print(f"Fields: {fieldnames}\n")

    missing = [r for r in rows if not r.get("english_name", "")]
    print(f"Missing english_name: {len(missing)}\n")

    updated = 0
    not_found_list = []

    for row in rows:
        if row.get("english_name", ""):
            continue  # Already has data

        filename = row.get("current_filename", "")
        pdf_title = row.get("pdf_title", "")
        existing_notes = row.get("notes", "")

        # Already has BGG ID in notes but missing names? Look up directly
        bgg_id_match = re.search(r"BGG ID:\s*(\d+)", existing_notes)
        if bgg_id_match:
            bgg_id = bgg_id_match.group(1)
            print(f"[{filename}] Looking up existing BGG ID: {bgg_id}")
            time.sleep(REQUEST_DELAY)
            details = get_bgg_details(bgg_id)
            if details:
                row["english_name"] = details["primary_name"]
                if details["russian_names"]:
                    row["russian_names"] = "; ".join(details["russian_names"])
                if details.get("is_expansion"):
                    row["is_expansion"] = "yes"
                updated += 1
                print(
                    f"  -> {details['primary_name']} | "
                    f"{'; '.join(details['russian_names'][:2]) or '—'}"
                )
                continue

        # Strategy 1: Search by cleaned pdf_title
        search_name = clean_pdf_title(pdf_title)
        details = None

        if search_name:
            print(f"[{filename}] Searching by pdf_title: '{search_name}'")
            time.sleep(REQUEST_DELAY)
            results = search_bgg(search_name)

            if results:
                # Try to find a result whose name matches the query
                details = _find_best_match(search_name, results)

        # Strategy 2: Search by cleaned filename
        if not details:
            search_name_from_file = clean_filename(filename)
            if search_name_from_file and search_name_from_file != search_name:
                print(
                    f"[{filename}] Searching by filename: '{search_name_from_file}'"
                )
                time.sleep(REQUEST_DELAY)
                results = search_bgg(search_name_from_file)

                if results:
                    details = _find_best_match(
                        search_name_from_file, results, fallback_query=search_name
                    )

        if not details:
            print(f"[{filename}] NOT FOUND")
            not_found_list.append(filename)
            continue

        # Update row
        row["english_name"] = details["primary_name"]

        if details["russian_names"]:
            row["russian_names"] = "; ".join(details["russian_names"])
        elif search_name:
            # Use cleaned pdf_title as Russian name if it's Cyrillic
            if any("\u0400" <= c <= "\u04FF" for c in search_name):
                row["russian_names"] = search_name

        bgg_note = f"BGG ID: {details['bgg_id']}"
        if "BGG ID" not in existing_notes:
            row["notes"] = (
                f"{existing_notes}, {bgg_note}".strip(", ")
                if existing_notes
                else bgg_note
            )

        if details.get("is_expansion"):
            row["is_expansion"] = "yes"

        updated += 1
        rus = "; ".join(details["russian_names"][:2]) if details["russian_names"] else "—"
        print(
            f"  -> {details['primary_name']} | {rus} | BGG: {details['bgg_id']}"
        )

    # Summary
    print(f"\n{'=' * 60}")
    print(f"Updated: {updated}")
    print(f"Not found: {len(not_found_list)}")

    if not_found_list:
        print(f"\nNot found files:")
        for fn in not_found_list:
            print(f"  - {fn}")

    if not dry_run:
        write_csv(fieldnames, rows)
        print(f"\nCSV saved to {CSV_PATH}")
    else:
        print(f"\nDRY RUN — no changes saved. Remove --dry-run to apply.")


if __name__ == "__main__":
    main()
