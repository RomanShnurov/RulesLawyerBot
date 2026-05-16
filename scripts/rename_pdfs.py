"""
Rename PDF files based on inventory CSV.

This script reads rules_pdfs_inventory.csv and renames PDFs to English names.

Usage:
    uv run python scripts/rename_pdfs.py [--dry-run]

Flags:
    --dry-run: Show what would be renamed without actually renaming
"""
import argparse
import csv
import re
import shutil
from pathlib import Path


# Windows forbids: < > : " / \ | ? * and trailing dots/spaces
_WIN_ILLEGAL = {
    ":": " -",
    "/": "-",
    "\\": "-",
    "|": "-",
    "?": "",
    "*": "",
    '"': "'",
    "<": "(",
    ">": ")",
}


def sanitize_for_windows(name: str) -> str:
    """Replace Windows-illegal filename chars and collapse whitespace."""
    for bad, good in _WIN_ILLEGAL.items():
        name = name.replace(bad, good)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name


def rename_pdfs(dry_run: bool = True):
    """Rename PDF files based on inventory CSV.

    Args:
        dry_run: If True, only show what would be renamed
    """
    csv_path = Path("rules_pdfs_inventory.csv")
    pdf_dir = Path("rules_pdfs")

    if not csv_path.exists():
        print(f"❌ CSV file not found: {csv_path}")
        print(f"   Run scripts/analyze_pdfs.py first")
        return

    # Read CSV
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        print("⚠️  CSV file is empty")
        return

    print(f"📋 Loaded {len(rows)} entries from CSV\n")

    if dry_run:
        print("🔍 DRY RUN MODE - No files will be renamed\n")
    else:
        print("⚠️  LIVE MODE - Files WILL be renamed\n")

    rename_count = 0
    skip_count = 0

    for row in rows:
        current_name = row["current_filename"]
        english_name = row["english_name"].strip()
        is_expansion = row.get("is_expansion", "").lower() == "yes"
        parent_game = row.get("parent_game", "").strip()

        # Skip if no English name provided
        if not english_name:
            print(f"⏭️  Skipping '{current_name}' (no English name provided)")
            skip_count += 1
            continue

        # Build new filename
        if is_expansion and parent_game:
            # Avoid "Parent - Parent: Subtitle" double-prefix when english_name already starts with parent
            if english_name.lower().startswith(parent_game.lower()):
                raw = english_name
            else:
                raw = f"{parent_game} - {english_name}"
        else:
            raw = english_name
        new_name = sanitize_for_windows(raw) + ".pdf"

        # Skip if already correct
        if current_name == new_name:
            print(f"✅ '{current_name}' (already correct)")
            continue

        old_path = pdf_dir / current_name
        new_path = pdf_dir / new_name

        # Check if file exists
        if not old_path.exists():
            # If the target already exists, this row was renamed in a prior run — treat as done
            if new_path.exists():
                print(f"✅ '{current_name}' already renamed to '{new_name}'")
                continue
            print(f"❌ '{current_name}' not found in {pdf_dir}")
            skip_count += 1
            continue

        # Detect case-only rename (Windows is case-insensitive — same file)
        case_only_rename = (
            old_path.exists()
            and new_path.exists()
            and current_name.lower() == new_name.lower()
        )

        # Check if target name already exists (and it's a different file)
        if new_path.exists() and not case_only_rename:
            print(f"⚠️  Cannot rename '{current_name}' → '{new_name}' (target exists)")
            skip_count += 1
            continue

        # Rename
        print(f"📝 '{current_name}' → '{new_name}'")

        if not dry_run:
            if case_only_rename:
                # Two-step rename to force case change on case-insensitive filesystems
                temp_path = pdf_dir / (current_name + ".tmprename")
                old_path.rename(temp_path)
                temp_path.rename(new_path)
            else:
                shutil.move(str(old_path), str(new_path))

        rename_count += 1

    print(f"\n{'=' * 60}")
    print(f"✅ Renamed: {rename_count}")
    print(f"⏭️  Skipped: {skip_count}")

    if dry_run:
        print(f"\n💡 Run without --dry-run to actually rename files:")
        print(f"   uv run python scripts/rename_pdfs.py")
    else:
        print(f"\n✅ Renaming complete!")
        print(f"\nNext step:")
        print(f"   uv run python scripts/generate_games_index.py")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Rename PDF files based on inventory CSV")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Show what would be renamed without actually renaming (default: True)"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually rename files (overrides --dry-run)"
    )

    args = parser.parse_args()

    # If --execute is provided, set dry_run to False
    dry_run = not args.execute

    rename_pdfs(dry_run=dry_run)
