"""One-off CSV cleanup: remove 4 duplicate rows and patch 5 ambiguous rows.

After this runs, all (english_name, parent_game, is_expansion) target combinations
in rules_pdfs_inventory.csv are unique, so rename_pdfs.py produces no collisions.
"""
import csv
import sys
from pathlib import Path

CSV = Path("rules_pdfs_inventory.csv")
PDF_DIR = Path("rules_pdfs")

# (current_filename, action) — action='delete' removes the row AND the PDF file
TO_DELETE = [
    "QH_Rule_RUS.pdf",                                  # dup of 13-ghosts.pdf
    "DECRYPTO_RULES_RU.pdf",                            # dup of DECRYPTO_RULES_RUS.pdf
    "kosmicheskie-dalnoboyschiki-keep-on-trucking.pdf", # byte-identical to galaxy-trucker-keep-on-trucking.pdf
    "bullet-star.pdf",                                  # shorter (16p) variant of bullet.pdf (24p), same BGG
]

# current_filename -> dict of field overrides
PATCHES = {
    # Conflict of Heroes: solo-rules expansion shared base game's english_name
    "probuzhdenie-medvedya-dopolnenie-dlya-solo-igry.pdf": {
        "english_name": "Conflict of Heroes: Awakening the Bear – Solo Expansion",
        "is_expansion": "yes",
        "parent_game": "Conflict of Heroes: Awakening the Bear – Operation Barbarossa 1941 (Third Edition)",
    },
    # La Famiglia: variant rules for 2-3 players
    "LaFam2-3-Player_Rules_RUS_web.pdf": {
        "english_name": "La Famiglia: The Great Mafia War (2-3 Player)",
    },
    # NOIR: special "Major Grom" edition
    "noir-major-grom.pdf": {
        "english_name": "NOIR: Deductive Mystery Game (Major Grom)",
    },
    # Senjutsu: two expansion rulebooks miscategorized as base game
    "Senjutsu_expansions_compressed.pdf": {
        "english_name": "Senjutsu: Battle for Japan – Expansions",
        "is_expansion": "yes",
        "parent_game": "Senjutsu: Battle For Japan",
    },
    "Senjutsu_thorns_rule.pdf": {
        "english_name": "Senjutsu: Battle for Japan – Thorns",
        "is_expansion": "yes",
        "parent_game": "Senjutsu: Battle For Japan",
    },
    # Tortuga 2199: solo rules variant
    "Tortuga_rules_solo_Rus.pdf": {
        "english_name": "Tortuga 2199 (Solo)",
    },
}


def main():
    with open(CSV, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    initial = len(rows)
    new_rows = []
    deleted_rows = 0
    patched_rows = 0

    for row in rows:
        name = row["current_filename"]
        if name in TO_DELETE:
            deleted_rows += 1
            print(f"  - delete row: {name}")
            continue
        if name in PATCHES:
            for k, v in PATCHES[name].items():
                row[k] = v
            patched_rows += 1
            print(f"  ~ patch row : {name}")
        new_rows.append(row)

    # Write back (preserve BOM for Excel compatibility)
    with open(CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(new_rows)

    # Delete PDF files
    deleted_files = 0
    for name in TO_DELETE:
        p = PDF_DIR / name
        if p.exists():
            p.unlink()
            print(f"  x delete pdf: {name}")
            deleted_files += 1
        else:
            print(f"  ? not found : {name}")

    print()
    print(f"CSV: {initial} -> {len(new_rows)} rows ({deleted_rows} deleted, {patched_rows} patched)")
    print(f"PDFs deleted: {deleted_files}/{len(TO_DELETE)}")


if __name__ == "__main__":
    main()
