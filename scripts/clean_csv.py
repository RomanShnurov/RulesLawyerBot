"""
Clean rules_pdfs_inventory.csv:
1. Remove Ukrainian/Bulgarian game names from russian_names column
2. Remove CSV quote characters by stripping commas from preview text
"""

import csv
import io
from pathlib import Path

CSV_PATH = Path("rules_pdfs_inventory.csv")

# Ukrainian-specific characters (not found in Russian)
UA_CHARS = set("ІіЇїЄєҐґ")

# Names that don't have Ukrainian-specific chars but are still not Russian
# (Ukrainian without special chars, Bulgarian, etc.)
NON_RUSSIAN_NAMES = {
    "Bullet. Головоломний шутер",  # Ukrainian: -ний instead of -ный
    "Живопис",  # Ukrainian for "живопись"
    "Драфтозаври",  # Ukrainian: -и instead of -ы
    "Словесни Клопки",  # Ukrainian
    "Криле: Европа",  # Bulgarian/other Slavic
    "Изгубените руини на Арнак",  # Bulgarian
    "Крихітні Містечка",  # Ukrainian (also caught by chars)
}

# Special cases: filenames where the ONLY name is Ukrainian
RUSSIAN_REPLACEMENTS = {
    "Distant Skies rulebook RUS_compressed.pdf": "Спящие боги: Далёкие небеса",
    "level-10.pdf": "Уровень 10",
}


def has_ukrainian_chars(text: str) -> bool:
    """Check if text contains Ukrainian-specific characters."""
    return bool(set(text) & UA_CHARS)


def is_non_russian(name: str) -> bool:
    """Check if a game name is non-Russian."""
    name = name.strip()
    if has_ukrainian_chars(name):
        return True
    if name in NON_RUSSIAN_NAMES:
        return True
    return False


def clean_russian_names(filename: str, names_field: str) -> str:
    """Remove non-Russian names from the russian_names field."""
    names_field = names_field.strip()
    if not names_field:
        return names_field

    parts = [n.strip() for n in names_field.split(";")]
    russian_parts = [p for p in parts if p and not is_non_russian(p)]

    if not russian_parts:
        fn = filename.strip()
        if fn in RUSSIAN_REPLACEMENTS:
            return RUSSIAN_REPLACEMENTS[fn]
        print(f"  WARNING: No Russian name found: {fn} -> {names_field}")
        return names_field

    return "; ".join(russian_parts)


def main():
    content = CSV_PATH.read_text(encoding="utf-8")
    lines = content.splitlines()

    header = lines[0]
    new_lines = [header]

    ua_cleaned = 0
    quotes_cleaned = 0

    for line in lines[1:]:
        if not line.strip():
            new_lines.append(line)
            continue

        # Parse using csv reader to handle quoted fields properly
        reader = csv.reader(io.StringIO(line))
        fields = next(reader)

        if len(fields) < 9:
            new_lines.append(line)
            continue

        filename = fields[0]
        russian_names = fields[2]
        preview = fields[7]

        # 1. Clean non-Russian names from russian_names
        original_names = russian_names.strip()
        cleaned_names = clean_russian_names(filename, russian_names)
        if cleaned_names != original_names:
            ua_cleaned += 1
            print(f"  UA: {filename.strip()}")
            print(f"    {original_names}")
            print(f"    -> {cleaned_names}")
            fields[2] = f" {cleaned_names}"

        # 2. Remove commas from preview to eliminate CSV quoting
        if "," in preview:
            clean_preview = preview.replace(",", " ")
            fields[7] = clean_preview
            quotes_cleaned += 1

        # Reconstruct line with same padding
        widths = [56, 83, 82, 13, 12, 5, 70, 103, 0]
        padded = []
        for i, (field, width) in enumerate(zip(fields, widths)):
            if width > 0:
                padded.append(field.ljust(width))
            else:
                padded.append(field)
        new_lines.append(",".join(padded))

    CSV_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    print(f"\nNon-Russian names cleaned: {ua_cleaned}")
    print(f"Preview fields de-quoted: {quotes_cleaned}")


if __name__ == "__main__":
    main()
