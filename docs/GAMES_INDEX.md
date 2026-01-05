# Games Index (games_index.json)

## 📖 Purpose

`rules_pdfs/games_index.json` is a reference file for **bilingual game search**. It enables users to search for rulebooks in both Russian and English.

## 🎯 Benefits

**Without index:**
- ❌ LLM guesses name translation (unreliable for 100+ games)
- ❌ "Крылья" (Wings) may not find "Wingspan.pdf"
- ❌ Each query wastes tokens on translation

**With index:**
- ✅ Accurate Russian ↔ English name matching
- ✅ Support for multiple name variants (official, transliteration, slang)
- ✅ Fast lookup without token usage
- ✅ Tags for game categorization

## 📄 File Structure

```json
{
  "games": [
    {
      "english_name": "Dead Cells",
      "russian_names": ["Мёртвые клетки", "Дед Селлс"],
      "pdf_files": ["Dead Cells.pdf"],
      "tags": ["roguelike", "card game", "deck-building"]
    }
  ]
}
```

### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `english_name` | string | ✅ Yes | Official English game name (must match PDF filename without extension) |
| `russian_names` | array[string] | ✅ Yes | List of all possible Russian variants (official name, transliteration, slang) |
| `pdf_files` | array[string] | ✅ Yes | List of associated PDF files (core rules, FAQ, expansions) |
| `tags` | array[string] | ⚪ No | Tags for categorization (mechanics, theme) |

## ✏️ Adding a New Game

### Step 1: Prepare PDF file

```bash
# File must be named in English
rules_pdfs/
└── Wingspan.pdf
```

### Step 2: Add entry to games_index.json

```json
{
  "games": [
    {
      "english_name": "Wingspan",
      "russian_names": [
        "Крылья",
        "Вингспан",
        "Размах крыльев"
      ],
      "pdf_files": ["Wingspan.pdf"],
      "tags": ["engine-building", "cards", "birds"]
    }
  ]
}
```

### Step 3: Test search

Start the bot and try:
- `/games Крылья` → should find Wingspan
- `/games wingspan` → should find Wingspan
- Question: "How to play Wingspan?" → should find Wingspan rules

## 📚 Examples for Different Scenarios

### 1. Game with single rulebook

```json
{
  "english_name": "Azul",
  "russian_names": ["Азул", "Azul"],
  "pdf_files": ["Azul.pdf"],
  "tags": ["abstract", "puzzle", "tiles"]
}
```

### 2. Game with expansions and FAQ

```json
{
  "english_name": "Gloomhaven",
  "russian_names": [
    "Глумхейвен",
    "Мрачная гавань",
    "Gloomhaven"
  ],
  "pdf_files": [
    "Gloomhaven.pdf",
    "Gloomhaven - Forgotten Circles.pdf",
    "Gloomhaven - FAQ.pdf"
  ],
  "tags": ["dungeon crawler", "campaign", "legacy", "cooperative"]
}
```

### 3. Game with multiple editions

```json
{
  "english_name": "Brass Birmingham",
  "russian_names": ["Brass Birmingham", "Брасс Бирмингем"],
  "pdf_files": ["Brass Birmingham.pdf"],
  "tags": ["economic", "industry", "heavy"]
},
{
  "english_name": "Brass Lancashire",
  "russian_names": ["Brass Lancashire", "Брасс Ланкашир"],
  "pdf_files": ["Brass Lancashire.pdf"],
  "tags": ["economic", "industry", "heavy"]
}
```

### 4. Game with transliteration

```json
{
  "english_name": "Carcassonne",
  "russian_names": [
    "Каркассон",
    "Каркассонн",
    "Carcassonne"
  ],
  "pdf_files": [
    "Carcassonne.pdf",
    "Carcassonne - Inns and Cathedrals.pdf"
  ],
  "tags": ["tiles", "area control", "family"]
}
```

## 🔍 How Search Works

When user asks: **"How to move in Dead Cells?"** (in Russian: "Как ходить в Мёртвых клетках?")

1. Bot calls `find_game_by_name("Мёртвые клетки")`
2. Function searches in `games_index.json`:
   - Checks `english_name`: "Dead Cells" ❌ (no match)
   - Checks `russian_names`: ["Мёртвые клетки", "Дед Селлс"] ✅ (found!)
3. Returns game information:
   ```json
   {
     "found": true,
     "match_type": "exact",
     "game": {
       "english_name": "Dead Cells",
       "pdf_files": ["Dead Cells.pdf"]
     }
   }
   ```
4. Bot opens `Dead Cells.pdf` and searches for movement rules

## 💡 Best Practices

### Russian Names

1. **Always include official Russian name** (if exists)
2. **Add popular variants:**
   - Transliteration of English name
   - Abbreviations (if any)
   - Slang variants from community

```json
"russian_names": [
  "Ужас Аркхэма",           // Official Russian
  "Arkham Horror",           // Transliteration
  "Аркхем Хоррор",          // Alternative transliteration
  "Ужас Аркхема"            // Variant
]
```

### Tags

Use tags for:
- **Mechanics:** "deck-building", "worker placement", "cooperative"
- **Theme:** "fantasy", "sci-fi", "historical"
- **Weight:** "family", "medium", "heavy"
- **Genre:** "euro", "ameritrash", "party"

```json
"tags": ["cooperative", "legacy", "campaign", "fantasy", "dungeon crawler"]
```

## 🛠️ Tools

### Auto-generation (future improvement)

You can create a script to automatically generate `games_index.json` from:
- Existing PDF files in `rules_pdfs/`
- BoardGameGeek API for Russian names
- Manual CSV file with mappings

**Script already created:** `scripts/generate_games_index.py`

### Index Validation

Make sure that:
- ✅ All files from `pdf_files` actually exist in `rules_pdfs/`
- ✅ `english_name` matches the main PDF name
- ✅ No duplicates in `russian_names` between games
- ✅ JSON is valid (use `jq` or IDE with validation)

```bash
# Check JSON validity
jq empty rules_pdfs/games_index.json

# List all games
jq '.games[].english_name' rules_pdfs/games_index.json
```

## 🚨 Important Notes

1. **Index file is NOT required** — bot works without it, using `search_filenames()` as fallback
2. **But for 100+ games index is CRITICAL** for accurate bilingual search
3. **Update index every time** you add a new game
4. **Store index in Git** together with the project for synchronization

## 📝 Complete Index Example

```json
{
  "games": [
    {
      "english_name": "7 Wonders",
      "russian_names": ["7 чудес", "Семь чудес", "Seven Wonders"],
      "pdf_files": ["7 Wonders.pdf", "7 Wonders - Leaders.pdf"],
      "tags": ["drafting", "civilization", "family"]
    },
    {
      "english_name": "Agricola",
      "russian_names": ["Агрикола", "Agricola"],
      "pdf_files": ["Agricola.pdf"],
      "tags": ["worker placement", "farming", "euro"]
    },
    {
      "english_name": "Dead Cells",
      "russian_names": ["Мёртвые клетки", "Дед Селлс"],
      "pdf_files": ["Dead Cells.pdf"],
      "tags": ["roguelike", "card game", "deck-building"]
    }
  ]
}
```

---

**Done!** Now your bot understands both Russian and English game names. 🎮
