# BoardGameGeek API Setup

## Overview

The `scripts/generate_games_index.py` script uses the BoardGameGeek (BGG) API to automatically fetch game metadata including Russian names, categories, and mechanics for board games in your collection.

## Prerequisites

Since BGG API now requires authentication, you need to register your application and obtain an API token.

## Setup Steps

### 1. Register Your Application

1. Go to https://boardgamegeek.com/applications
2. Click "Register New Application"
3. Choose license type:
   - **Non-commercial**: For personal use, no revenue generation
   - **Commercial**: If your bot generates revenue or shows ads
4. Fill in application details:
   - **Application Name**: RulesLawyerBot (or your custom name)
   - **Description**: Telegram bot for board game rules assistance
   - **Website**: Your GitHub repo or project URL (optional)
5. Submit and wait for approval
6. Once approved, you'll receive your **Application Token**

### 2. Add Token to Environment

1. Copy your application token from https://boardgamegeek.com/applications
2. Open your `.env` file in the project root
3. Add or update the following line:
   ```bash
   BGG_API_TOKEN=your-token-here
   ```
4. Save the file

### 3. Run the Script

```bash
uv run python scripts/generate_games_index.py
```

The script will:
- Scan all PDF files in `rules_pdfs/` directory
- For each game, query BGG API for metadata
- Extract Russian names, categories, and mechanics
- Generate/update `rules_pdfs/games_index.json`

## Expected Output

```
🎮 BoardGameGeek API games_index.json Generator

📖 Loaded existing index: 3 games

🔍 Found 3 PDF files

🔎 Searching BGG for 'Dead Cells'...
✅ Dead Cells
   Russian names: Мёртвые клетки, Дед Селлс

✅ Index saved to rules_pdfs\games_index.json
📊 Total games: 3
```

## Troubleshooting

### No BGG_API_TOKEN found

**Error:**
```
⚠️  No BGG_API_TOKEN found in .env file
   Register at https://boardgamegeek.com/applications
```

**Solution:** Make sure you've added `BGG_API_TOKEN` to your `.env` file.

### 401 Unauthorized Error

**Error:**
```
❌ Error searching 'GameName': 401 Client Error: Unauthorized
```

**Possible causes:**
- Invalid or expired token
- Application not approved yet
- Token not properly formatted in `.env`

**Solution:**
1. Verify your token at https://boardgamegeek.com/applications
2. Check that there are no extra spaces in `.env` file
3. Ensure your application is approved

### Game Not Found in BGG

**Warning:**
```
⚠️  'GameName' not found in BGG
```

This is normal for:
- Games with non-English names (try English name in filename)
- Very new or obscure games not in BGG database
- Expansions or fan-made content

The script will create a basic entry with just the filename as the name.

## API Limits

BGG API has usage limits depending on your license type. The script:
- Adds 1-second delay between requests
- Caches existing game data to minimize API calls
- Only queries BGG for new games not already in the index

Monitor your usage at: https://boardgamegeek.com/applications

## References

- [BGG API Documentation](https://boardgamegeek.com/using_the_xml_api)
- [BGG XML API2 Reference](https://boardgamegeek.com/wiki/page/BGG_XML_API2)
