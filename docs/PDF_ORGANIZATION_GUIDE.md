# PDF Organization Guide

Complete guide for organizing your PDF rulebooks collection.

## Overview

This guide walks you through organizing PDFs downloaded from Russian board game sites (Gaga Games, lavkaigr, etc.) into a structure that RulesLawyerBot can search efficiently.

## Goals

1. **English filenames** for universal compatibility and BGG API matching
2. **Russian names in index** for user-facing search
3. **Flat directory structure** for simple file management
4. **Automated index generation** using BoardGameGeek API

## Target Structure

```
rules_pdfs/
├── games_index.json                    # Auto-generated index
├── Dead Cells.pdf                      # Main games (English names)
├── Wingspan.pdf
├── Gloomhaven.pdf
├── Gloomhaven - Forgotten Circles.pdf  # Expansion format
└── Arkham Horror - FAQ.pdf             # FAQ/errata format
```

## Step-by-Step Process

### Step 1: Analyze Current PDFs

Run the analysis script to understand what you have:

```bash
uv run python scripts/analyze_pdfs.py
```

This will:
- Scan all PDF files in `rules_pdfs/`
- Extract metadata (title, page count, first page preview)
- Create `rules_pdfs_inventory.csv` for manual mapping

### Step 2: Auto-fill English Names (NEW!)

Use BGG API to automatically fill English names with **smart similarity matching**:

```bash
uv run python scripts/auto_fill_inventory.py
```

**How it works:**
1. Searches BGG for each PDF filename
2. Calculates **similarity score** between filename and BGG results
3. **Auto-selects** if similarity ≥ 80% (configurable)
4. Asks for manual selection only when similarity is low
5. **Saves progress after each game** (safe to interrupt with Ctrl+C)
6. Skips already filled entries automatically (resume support)

**What it does:**
- ✅ Searches BGG for each PDF filename
- ✅ **Smart matching** with similarity scores (🟢 ≥80%, 🟡 ≥60%, 🔴 <60%)
- ✅ Auto-fills `english_name` column
- ✅ Auto-fills `russian_names` from BGG alternate names
- ✅ Detects expansions (heuristic)
- ✅ Saves BGG ID in notes
- ✅ Skips already filled entries

**Example output with auto-matching:**
```
[1/10] 🔎 Searching for: 'dead cells'
   🎯 Auto-matched: Dead Cells: The Rogue-Lite Board Game (2021) - 95% similarity
   ✅ Updated: Dead Cells: The Rogue-Lite Board Game
      Russian: Мёртвые клетки

[2/10] 🔎 Searching for: 'wingspan'
   🎯 Auto-matched: Wingspan (2019) - 100% similarity
   ✅ Updated: Wingspan
      Russian: Крылья

[3/10] 🔎 Searching for: 'complex game name'
   ⚠️  Best match: Some Game - 65% similarity (below 80% threshold)
   👤 Manual selection required

📄 File: complex_game_name.pdf
🔍 Query: 'complex game name'
Found 3 results on BGG (sorted by similarity):

1. 🟡 Some Game (2021) - 65% match
   Russian: Какая-то игра
   Tags: Strategy, Deck Building

2. 🔴 Another Game (2020) - 45% match
   Tags: Action

3. 🔴 Third Game (2019) - 30% match

0. Skip (I'll fill manually)
s. Search with different query

Select game [1-3/0/s]:
```

**Adjust similarity threshold:**
```bash
# More strict (90% minimum for auto-match)
uv run python scripts/auto_fill_inventory.py --similarity-threshold=0.9

# More lenient (70% minimum for auto-match)
uv run python scripts/auto_fill_inventory.py --similarity-threshold=0.7
```

**Fast mode (skip similarity matching):**
```bash
uv run python scripts/auto_fill_inventory.py --auto-accept
```
- Automatically selects first BGG result (ignores similarity)
- Faster but less accurate
- Good for well-known games with obvious names

### Step 3: Manual Review (if needed)

Open `rules_pdfs_inventory.csv` and verify/fix:

| Column | Description | Example |
|--------|-------------|---------|
| `current_filename` | Current PDF name | `Мёртвые_клетки_правила.pdf` |
| `english_name` | **English name from BGG** | `Dead Cells` |
| `russian_names` | Comma-separated Russian variants | `Мёртвые клетки, Дед Селлс` |
| `is_expansion` | `yes` or `no` | `no` |
| `parent_game` | Parent game name (if expansion) | (empty) |
| `notes` | Any notes | (optional) |

**Tips for filling in `english_name`:**
1. Search the game on [BoardGameGeek](https://boardgamegeek.com)
2. Copy the **exact English name** from BGG (this helps BGG API matching)
3. For expansions:
   - Set `is_expansion` to `yes`
   - Put the **expansion name** in `english_name` (not full title)
   - Put **parent game name** in `parent_game`
   - Example:
     - Parent: `english_name = "Gloomhaven"`, `is_expansion = no`
     - Expansion: `english_name = "Forgotten Circles"`, `is_expansion = yes`, `parent_game = "Gloomhaven"`
     - Result: `Gloomhaven - Forgotten Circles.pdf`

### Step 4: Preview Renaming (Dry Run)

Check what will be renamed without actually renaming:

```bash
uv run python scripts/rename_pdfs.py --dry-run
```

This shows:
```
📝 'Мёртвые_клетки_правила.pdf' → 'Dead Cells.pdf'
📝 'Крылья_базовая_игра.pdf' → 'Wingspan.pdf'
```

### Step 5: Execute Renaming

If the preview looks correct, run the actual rename:

```bash
uv run python scripts/rename_pdfs.py --execute
```

**⚠️ WARNING**: This permanently renames files. Make a backup first!

### Step 6: Generate Games Index with BGG API

Now use BoardGameGeek API to fetch metadata (Russian names, categories, mechanics):

```bash
uv run python scripts/generate_games_index.py
```

This will:
- Scan all PDF files in `rules_pdfs/`
- Query BGG API for each game
- Extract Russian names from BGG database
- Fetch categories and mechanics
- Generate `rules_pdfs/games_index.json`

**Prerequisites:**
- `BGG_API_TOKEN` in your `.env` file (see [BGG API Setup](BGG_API_SETUP.md))

**Example output:**
```
🎮 BoardGameGeek API games_index.json Generator

📖 Loaded existing index: 0 games

🔍 Found 3 PDF files

🔎 Searching BGG for 'Dead Cells'...
✅ Dead Cells
   Russian names: Мёртвые клетки, Дед Селлс

✅ Index saved to rules_pdfs/games_index.json
📊 Total games: 3
```

### Step 7: Manual Corrections (Optional)

If some games weren't found in BGG or Russian names are wrong, manually edit `rules_pdfs/games_index.json`:

```json
{
  "games": [
    {
      "english_name": "Dead Cells",
      "russian_names": ["Мёртвые клетки", "Дед Селлс"],
      "pdf_files": ["Dead Cells.pdf"],
      "tags": ["dungeon-crawler", "deck-building"],
      "bgg_id": "291457"
    }
  ]
}
```

**Tips:**
- Add common misspellings to `russian_names` for better search
- Add transliterations: `"Вингспан"` + `"Wingspan"`
- Add slang names used by players

## Naming Conventions

### Main Games
```
{EnglishName}.pdf
```
Examples:
- ✅ `Dead Cells.pdf`
- ✅ `Wingspan.pdf`
- ✅ `Arkham Horror.pdf`
- ❌ `Мёртвые клетки.pdf` (use English)
- ❌ `dead_cells.pdf` (use Title Case with spaces)

### Expansions
```
{ParentGame} - {ExpansionName}.pdf
```
Examples:
- ✅ `Gloomhaven - Forgotten Circles.pdf`
- ✅ `Wingspan - European Expansion.pdf`
- ❌ `Forgotten Circles.pdf` (missing parent game)

### FAQ and Errata
```
{GameName} - FAQ.pdf
{GameName} - Errata.pdf
```
Examples:
- ✅ `Arkham Horror - FAQ.pdf`
- ✅ `Gloomhaven - Errata.pdf`

### Multiple Editions
```
{GameName} ({Edition}).pdf
```
Examples:
- `Arkham Horror (3rd Edition).pdf`
- `Twilight Imperium (4th Edition).pdf`

## Troubleshooting

### Game Not Found in BGG

**Problem:**
```
⚠️  'MyGame' not found in BGG
```

**Solutions:**
1. Check if the English name exactly matches BGG (including punctuation)
2. Try searching on BGG manually: https://boardgamegeek.com
3. For very new/obscure games, manually add entry to `games_index.json`

### Multiple Games with Similar Names

**Problem:** BGG returns wrong game (e.g., "Dead Cells" board game vs video game adaptation)

**Solution:**
1. After running `generate_games_index.py`, check the `bgg_id` in the output
2. Verify on BGG: `https://boardgamegeek.com/boardgame/{bgg_id}`
3. If wrong, manually edit `games_index.json` with correct `bgg_id` and re-run script

### PDF Filename Already Exists

**Problem:**
```
⚠️  Cannot rename 'game.pdf' → 'Dead Cells.pdf' (target exists)
```

**Solution:**
1. Check if you have duplicates (same game, different language/edition)
2. Use edition naming: `Dead Cells (Russian).pdf`, `Dead Cells (English).pdf`
3. Or move one to a backup folder

## Advanced: Batch Operations

### Find Games Missing from BGG

Check which games in your inventory don't have BGG data:

```python
# In Python console:
import json
from pathlib import Path

index_path = Path("rules_pdfs/games_index.json")
with open(index_path) as f:
    data = json.load(f)

missing_bgg = [g for g in data["games"] if "bgg_id" not in g]
print(f"Games missing BGG ID: {len(missing_bgg)}")
for game in missing_bgg:
    print(f"  - {game['english_name']}")
```

### Validate Index Structure

```bash
python -c "import json; print('✅ Valid JSON' if json.load(open('rules_pdfs/games_index.json')) else '❌ Invalid')"
```

## Best Practices

1. **Backup before renaming**: Copy `rules_pdfs/` to `rules_pdfs_backup/`
2. **Incremental approach**: Start with 5-10 games, verify bot works, then add more
3. **Consistent naming**: Always use Title Case with spaces
4. **Document special cases**: Add notes in CSV for games with unusual names
5. **Test search**: After setup, test bot with Russian queries to verify index works

## Files Reference

- `scripts/analyze_pdfs.py` - Analyze current PDFs and create inventory CSV
- `scripts/auto_fill_inventory.py` - Auto-fill CSV with BGG API (NEW!)
- `scripts/rename_pdfs.py` - Rename PDFs based on inventory CSV
- `scripts/generate_games_index.py` - Generate games_index.json using BGG API
- `rules_pdfs_inventory.csv` - Manual mapping (created by analyze_pdfs.py, auto-filled by auto_fill_inventory.py)
- `rules_pdfs/games_index.json` - Searchable index (created by generate_games_index.py)

## Example Workflow

```bash
# 1. Analyze PDFs
uv run python scripts/analyze_pdfs.py

# 2. Auto-fill English names with BGG API (NEW!)
uv run python scripts/auto_fill_inventory.py
# Interactive mode: select correct game for each PDF

# 3. (Optional) Manual edits in Excel
# Review rules_pdfs_inventory.csv, fix any errors

# 4. Preview renaming
uv run python scripts/rename_pdfs.py --dry-run

# 5. Execute renaming
uv run python scripts/rename_pdfs.py --execute

# 6. Generate BGG index
uv run python scripts/generate_games_index.py

# 7. Test bot
python -m src.rules_lawyer_bot.main
# Send message: "Что такое Dead Cells?"
```

## Support

If you encounter issues, check:
- [GAMES_INDEX.md](GAMES_INDEX.md) - Games index format and structure
- [BGG_API_SETUP.md](BGG_API_SETUP.md) - BGG API configuration
- [QUICKSTART.md](QUICKSTART.md) - Bot setup guide
