"""
Fix corrupted rules_pdfs_inventory.csv.

The corruption happened because csv.reader without skipinitialspace=True
incorrectly handled quoted preview fields, splitting them at commas.

Recovery strategy:
1. Re-extract PDF metadata (pages, title, preview) from actual files
2. Extract game data (english_name, russian_names, etc.) from corrupted CSV
3. Find BGG IDs scattered across wrong fields in corrupted lines
4. Write a clean CSV
"""

import csv
import io
import re
from pathlib import Path

from pypdf import PdfReader

CSV_PATH = Path("rules_pdfs_inventory.csv")
PDF_DIR = Path("rules_pdfs")


def extract_pdf_info(pdf_path: Path) -> dict:
    """Extract basic info from PDF file."""
    try:
        reader = PdfReader(pdf_path)
        metadata = reader.metadata or {}
        first_page_text = ""
        if len(reader.pages) > 0:
            first_page_text = reader.pages[0].extract_text()[:500]
        return {
            "pages": len(reader.pages),
            "pdf_title": (metadata.get("/Title", "") or "").strip(),
            "preview": first_page_text.replace("\n", " ")[:100],
        }
    except Exception as e:
        return {"pages": 0, "pdf_title": "", "preview": f"Error: {e}"}


def read_corrupted_csv() -> dict[str, dict]:
    """Read corrupted CSV and extract game data per filename."""
    data = {}
    lines = CSV_PATH.read_text(encoding="utf-8").splitlines()

    for line in lines[1:]:
        if not line.strip():
            continue

        # Parse with skipinitialspace to handle the space-before-quote issue
        fields = list(csv.reader(io.StringIO(line), skipinitialspace=True))[0]

        if len(fields) < 7:
            continue

        filename = fields[0].strip()
        english_name = fields[1].strip()
        russian_names = fields[2].strip()
        is_expansion = fields[3].strip()
        parent_game = fields[4].strip()
        # fields[5] = pages (we'll get from PDF)
        # fields[6] = pdf_title (we'll get from PDF)

        # Find BGG ID - it might be in any field after the first 7
        notes = ""
        for f in fields:
            match = re.search(r"BGG ID:\s*\d+", f)
            if match:
                notes = match.group(0)
                break

        data[filename] = {
            "english_name": english_name,
            "russian_names": russian_names,
            "is_expansion": is_expansion,
            "parent_game": parent_game,
            "notes": notes,
        }

    return data


def main():
    print("Reading corrupted CSV...")
    game_data = read_corrupted_csv()
    print(f"  Extracted game data for {len(game_data)} files")

    bgg_count = sum(1 for d in game_data.values() if d["notes"])
    print(f"  Found BGG IDs: {bgg_count}")

    print("\nRe-extracting PDF metadata...")
    pdf_files = sorted(PDF_DIR.glob("*.pdf"))
    print(f"  Found {len(pdf_files)} PDF files")

    # Build combined data
    rows = []
    missing_bgg = []

    for pdf_file in pdf_files:
        filename = pdf_file.name
        pdf_info = extract_pdf_info(pdf_file)

        gd = game_data.get(filename, {})
        english_name = gd.get("english_name", "")
        russian_names = gd.get("russian_names", "")
        is_expansion = gd.get("is_expansion", "")
        parent_game = gd.get("parent_game", "")
        notes = gd.get("notes", "")

        if english_name and not notes:
            missing_bgg.append(filename)

        rows.append({
            "current_filename": filename,
            "english_name": english_name,
            "russian_names": russian_names,
            "is_expansion": is_expansion,
            "parent_game": parent_game,
            "pages": pdf_info["pages"],
            "pdf_title": pdf_info["pdf_title"],
            "preview": pdf_info["preview"],
            "notes": notes,
        })

    # Write clean CSV using DictWriter (standard quoting)
    fieldnames = [
        "current_filename", "english_name", "russian_names",
        "is_expansion", "parent_game", "pages",
        "pdf_title", "preview", "notes",
    ]

    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nWritten {len(rows)} rows to {CSV_PATH}")

    if missing_bgg:
        print(f"\nWARNING: {len(missing_bgg)} files with game data but no BGG ID:")
        for fn in missing_bgg[:10]:
            print(f"  {fn}")
        if len(missing_bgg) > 10:
            print(f"  ... and {len(missing_bgg) - 10} more")

    # Verify
    with open(CSV_PATH, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        check_rows = list(reader)
        ok = sum(1 for r in check_rows if len(r) == 9)
        print(f"\nVerification: {ok}/{len(check_rows)} rows have 9 fields")
        bgg_ok = sum(1 for r in check_rows if "BGG ID" in (r.get("notes", "") or ""))
        print(f"Rows with BGG ID in notes: {bgg_ok}")


if __name__ == "__main__":
    main()
