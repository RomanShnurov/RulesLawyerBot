# Schema-Guided Reasoning (SGR) Architecture

This document explains how Schema-Guided Reasoning is implemented in RulesLawyerBot to provide transparent, auditable, and controllable agent responses.

## Table of Contents

1. [Overview](#overview)
2. [What is Schema-Guided Reasoning?](#what-is-schema-guided-reasoning)
3. [Architecture](#architecture)
4. [Pydantic Schemas](#pydantic-schemas)
5. [Reasoning Process](#reasoning-process)
6. [Implementation Details](#implementation-details)
7. [User-Facing Features](#user-facing-features)
8. [Logging and Debugging](#logging-and-debugging)
9. [Configuration](#configuration)
10. [Examples](#examples)

---

## Overview

RulesLawyerBot uses Schema-Guided Reasoning (SGR) to transform the agent's thought process from an opaque "black box" into a transparent, structured pipeline. Every answer includes a complete reasoning chain that explains:

- How the question was understood
- What search strategy was chosen and why
- What information was found
- What follow-up searches were performed
- How confident the agent is in its answer

This enables:
- **Debugging**: Understand why the agent gave a specific answer
- **Quality Control**: Verify the agent follows correct reasoning patterns
- **User Trust**: Users can see the agent's thought process
- **Continuous Improvement**: Analyze reasoning chains to improve prompts

---

## What is Schema-Guided Reasoning?

Schema-Guided Reasoning is an approach where structured Pydantic schemas constrain and direct how an AI agent reasons through a problem. Instead of free-form text output, the agent produces structured JSON that follows a predefined schema.

### Traditional Agent Output
```
The attack rules in Super Fantasy Brawl are on page 12.
To attack, spend 2 action points and have line of sight to your target.
```

### SGR Agent Output
```json
{
  "query_analysis": {
    "query_type": "procedural",
    "game_name": "Super Fantasy Brawl",
    "primary_concepts": ["attack"],
    "reasoning": "User asks HOW to perform an action"
  },
  "search_plan": {
    "target_file": "Super Fantasy Brawl.pdf",
    "search_terms": ["атак|удар|бой"],
    "reasoning": "Using morphological roots for Russian text"
  },
  "primary_search_result": {
    "found": true,
    "completeness_score": 0.6,
    "referenced_concepts": ["action points", "line of sight"]
  },
  "follow_up_searches": [...],
  "answer": "To attack in Super Fantasy Brawl...",
  "confidence": 0.85
}
```

### Benefits of SGR

| Aspect | Traditional | SGR |
|--------|-------------|-----|
| Transparency | Low - only see final answer | High - see entire reasoning chain |
| Debugging | Difficult - must guess what went wrong | Easy - can trace each step |
| Consistency | Variable - depends on prompt | Structured - follows schema |
| Validation | None - any text is valid | Schema validation ensures completeness |
| Analytics | Limited | Rich - can analyze each field |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        User Question                             │
│                  "Как атаковать в SFB?"                         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     OpenAI Agents SDK                            │
│                                                                  │
│  Agent(                                                          │
│    instructions = SGR_INSTRUCTIONS,                              │
│    tools = [search_filenames, search_inside_file_ugrep, ...],   │
│    output_type = ReasonedAnswer  ◄── Pydantic Schema            │
│  )                                                               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    ReasonedAnswer Output                         │
│                                                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────────────┐     │
│  │QueryAnalysis│→ │ SearchPlan  │→ │SearchResultAnalysis  │     │
│  └─────────────┘  └─────────────┘  └──────────────────────┘     │
│                                              │                   │
│                                              ▼                   │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │              FollowUpSearch[] (0-3)                      │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              │                                   │
│                              ▼                                   │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │   Answer    │  │   Sources   │  │ Confidence  │              │
│  └─────────────┘  └─────────────┘  └─────────────┘              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Telegram Bot                                │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ format_reasoned_answer(answer, verbose=debug_mode)       │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              │                                   │
│              ┌───────────────┴───────────────┐                  │
│              ▼                               ▼                  │
│     [Normal Mode]                    [Debug Mode]               │
│     - Answer                         - Answer                   │
│     - Sources                        - Sources                  │
│     - Confidence                     - Confidence               │
│                                      - Full Reasoning Chain     │
└─────────────────────────────────────────────────────────────────┘
```

### File Structure

```
src/
├── agent/
│   ├── schemas.py      # Pydantic schemas for SGR
│   ├── definition.py   # Agent with output_type=ReasonedAnswer
│   └── tools.py        # Search tools
├── main.py             # Telegram bot with SGR formatting
└── utils/
    └── ...
```

---

## Pydantic Schemas

All schemas are defined in `src/agent/schemas.py`.

### QueryType (Enum)

Classifies the complexity of user questions:

```python
class QueryType(str, Enum):
    SIMPLE = "simple"           # Direct fact lookup
    CONTEXTUAL = "contextual"   # Needs related concepts
    PROCEDURAL = "procedural"   # Multi-step process
    CLARIFICATION = "clarification"  # Ambiguous question
```

**Examples:**
- SIMPLE: "What's the hand limit in Arkham Horror?"
- CONTEXTUAL: "How do I attack?" (needs AP, LOS context)
- PROCEDURAL: "How does a turn work?" (multi-step)
- CLARIFICATION: "What about movement?" (too vague)

### QueryAnalysis

Captures how the agent understands the user's question:

```python
class QueryAnalysis(BaseModel):
    original_question: str      # Exact user input
    interpreted_question: str   # Agent's interpretation
    query_type: QueryType       # Classification
    game_name: Optional[str]    # English game name
    primary_concepts: list[str] # Main concepts to search
    potential_dependencies: list[str]  # Related concepts
    language_detected: str      # "ru", "en", etc.
    reasoning: str              # Why classified this way
```

### SearchPlan

The agent's search strategy before execution:

```python
class SearchPlan(BaseModel):
    target_file: Optional[str]  # Which PDF to search
    search_terms: list[str]     # Keywords/regex patterns
    search_strategy: str        # "exact_match", "regex_morphology", "broad_scan"
    reasoning: str              # Why this strategy
```

### SearchResultAnalysis

Analysis of search results:

```python
class SearchResultAnalysis(BaseModel):
    search_term: str            # What was searched
    found: bool                 # Whether results found
    relevant_excerpts: list[str]    # Key text snippets
    page_references: list[str]      # Page numbers
    referenced_concepts: list[str]  # Terms that may need lookup
    completeness_score: float   # 0.0-1.0
    missing_context: list[str]  # What additional info needed
    reasoning: str              # Analysis of results
```

### FollowUpSearch

Records additional searches performed:

```python
class FollowUpSearch(BaseModel):
    concept: str                # What was searched for
    why_needed: str             # Why this follow-up was necessary
    search_terms: list[str]     # Terms used
    found_info: str             # Summary of findings
    contributed_to_answer: bool # Whether it was useful
```

### Source

A reference to where information was found:

```python
class Source(BaseModel):
    file: str       # PDF filename
    location: str   # Page or section
    excerpt: str    # Brief quote
```

### ReasonedAnswer (Main Output)

The complete structured response:

```python
class ReasonedAnswer(BaseModel):
    # Reasoning Chain
    query_analysis: QueryAnalysis
    search_plan: SearchPlan
    primary_search_result: SearchResultAnalysis
    follow_up_searches: list[FollowUpSearch]  # Max 3

    # The Answer
    answer: str                 # Complete answer
    answer_language: str        # Should match question
    sources: list[Source]       # References

    # Meta Information
    confidence: float           # 0.0-1.0
    limitations: list[str]      # Caveats
    suggestions: list[str]      # Related questions
```

---

## Reasoning Process

The agent follows a 5-step reasoning process, guided by instructions in `src/agent/definition.py`:

### Step 1: Query Analysis

The agent analyzes what the user is asking:

```
Input: "Как атаковать в Super Fantasy Brawl?"

Analysis:
- original_question: "Как атаковать в Super Fantasy Brawl?"
- interpreted_question: "Rules for performing an attack in SFB"
- query_type: PROCEDURAL (asks HOW to do something)
- game_name: "Super Fantasy Brawl" (translated from context)
- primary_concepts: ["attack", "combat"]
- potential_dependencies: ["action points", "line of sight", "damage"]
- language_detected: "ru"
- reasoning: "User asks HOW to attack - procedural question"
```

### Step 2: Search Planning

Before searching, the agent plans its strategy:

```
Plan:
- target_file: "Super Fantasy Brawl.pdf"
- search_terms: ["атак|удар|бой|сраж"]
- search_strategy: "regex_morphology"
- reasoning: "Russian text requires word roots to catch all forms"
```

**Search Strategies:**
- `exact_match`: For specific terms (English, proper nouns)
- `regex_morphology`: For Russian (handles word forms)
- `broad_scan`: When unsure, cast a wide net

### Step 3: Primary Search

Execute the search and analyze results:

```
Result:
- search_term: "атак|удар|бой"
- found: true
- relevant_excerpts: ["Атака: потратьте 2 ОД, выберите цель..."]
- page_references: ["стр. 12"]
- referenced_concepts: ["ОД", "линия видимости"]
- completeness_score: 0.6
- missing_context: ["What are ОД?", "How does LOS work?"]
- reasoning: "Found attack rules but they reference unexplained terms"
```

**Completeness Score Triggers:**
- `>= 0.8`: Answer is sufficient, no follow-up needed
- `0.5 - 0.8`: Consider follow-up for referenced concepts
- `< 0.5`: Follow-up searches required

### Step 4: Follow-up Searches

If completeness < 0.8 or referenced_concepts contains unexplained terms:

```
Follow-up 1:
- concept: "Action Points (ОД)"
- why_needed: "Attack cost mentioned but not explained"
- search_terms: ["очк.*действ|ОД"]
- found_info: "Each champion has 3 AP per activation"
- contributed_to_answer: true

Follow-up 2:
- concept: "Line of Sight"
- why_needed: "Attack requires LOS but rules not found"
- search_terms: ["лин.*вид|обзор|видимость"]
- found_info: "LOS is blocked by terrain and other figures"
- contributed_to_answer: true
```

**Limits:**
- Maximum 3 follow-up searches
- Only search if it adds value to the answer
- Track whether each search contributed

### Step 5: Synthesize Answer

Combine all findings into the final response:

```
answer: "Чтобы атаковать в Super Fantasy Brawl:
1. Потратьте 2 очка действия (у каждого чемпиона 3 ОД за активацию)
2. Выберите цель в линии видимости (не заблокированную террейном)
3. Бросьте кубики атаки..."

sources: [{file: "SFB.pdf", location: "стр. 12", excerpt: "Атака: ..."}]
confidence: 0.85
limitations: ["Не рассмотрены специальные атаки персонажей"]
suggestions: ["Как работает защита?", "Что такое критический удар?"]
```

---

## Implementation Details

### Agent Definition (`src/agent/definition.py`)

```python
from src.agent.schemas import ReasonedAnswer

agent = Agent(
    name="Board Game Referee",
    model=model,
    instructions=SGR_INSTRUCTIONS,  # Detailed reasoning steps
    tools=[
        search_filenames,
        search_inside_file_ugrep,
        read_full_document
    ],
    output_type=ReasonedAnswer,  # Forces structured output
)
```

The `output_type=ReasonedAnswer` parameter tells the OpenAI Agents SDK to:
1. Generate a JSON Schema from the Pydantic model
2. Instruct the LLM to output valid JSON matching that schema
3. Validate and parse the response into a Python object

### Message Handler (`src/main.py`)

```python
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... rate limiting, session setup ...

    result = await Runner.run(
        agent=rules_agent,
        input=message_text,
        session=session
    )

    # result.final_output is now a ReasonedAnswer object
    if isinstance(result.final_output, ReasonedAnswer):
        log_reasoning_chain(user.id, result.final_output)

        response_text = format_reasoned_answer(
            result.final_output,
            verbose=user_debug_mode.get(user.id, False)
        )
```

### Output Formatting

The `format_reasoned_answer()` function converts the structured output to Telegram-friendly text:

**Normal Mode:**
```
Чтобы атаковать в Super Fantasy Brawl...

📖 Источники: Super Fantasy Brawl.pdf (стр. 12)
✅ Уверенность: 85%
💡 См. также: Как работает защита?
```

**Debug Mode (verbose=True):**
```
Чтобы атаковать в Super Fantasy Brawl...

📖 Источники: Super Fantasy Brawl.pdf (стр. 12)
✅ Уверенность: 85%
💡 См. также: Как работает защита?

══════════════════════════════
REASONING CHAIN
══════════════════════════════

1. Query Analysis
  Type: procedural
  Game: Super Fantasy Brawl
  Interpreted: Правила выполнения атаки
  Concepts: attack, combat
  Dependencies: action points, line of sight
  Reasoning: User asks HOW to attack...

2. Search Plan
  File: Super Fantasy Brawl.pdf
  Terms: атак|удар|бой|сраж
  Strategy: regex_morphology
  Reasoning: Russian requires morphological roots

3. Primary Search
  Term: атак|удар|бой
  Found: Yes
  Completeness: 60%
  Excerpt 1: Атака: потратьте 2 ОД...
  References: ОД, линия видимости
  Analysis: Found rules but references unexplained terms

4. Follow-up Searches (2)
  [1] Action Points (ОД)
      Why: Attack cost mentioned but not explained
      Found: Each champion has 3 AP per activation...
      Useful: Yes
  [2] Line of Sight
      Why: Required for attack but not explained
      Found: LOS blocked by terrain and figures...
      Useful: Yes
```

---

## User-Facing Features

### Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message with instructions |
| `/debug` | Toggle verbose reasoning output |
| `/id` | Show user's Telegram ID |
| `/health` | Bot health status (admin only) |

### Debug Mode

Users can enable debug mode to see the full reasoning chain:

```
User: /debug
Bot: 🔍 Debug mode enabled

     You will now see the full reasoning chain:
     • How I understood your question
     • What searches I performed
     • Key findings from the rulebook
     • Additional context gathered

     Use /debug again to disable.
```

### Confidence Indicators

The bot shows confidence level with visual indicators:

| Confidence | Indicator | Meaning |
|------------|-----------|---------|
| >= 80% | ✅ | High confidence |
| 50-79% | ⚠️ | Medium confidence |
| < 50% | ❓ | Low confidence |

---

## Logging and Debugging

### Reasoning Chain Logging

Every response is logged with its complete reasoning chain:

```
INFO: [SGR] User 123456 - Reasoning Chain:
INFO:   [Query] Type: procedural, Game: Super Fantasy Brawl
INFO:   [Query] Interpreted: Правила выполнения атаки
INFO:   [Query] Concepts: ['attack', 'combat']
INFO:   [Plan] File: Super Fantasy Brawl.pdf, Strategy: regex_morphology
INFO:   [Plan] Terms: ['атак|удар|бой|сраж']
INFO:   [Search] Found: True, Completeness: 60%
INFO:   [Search] Referenced: ['ОД', 'линия видимости']
INFO:   [Follow-up 1] Action Points (ОД): True
INFO:   [Follow-up 2] Line of Sight: True
INFO:   [Result] Confidence: 85%
INFO:   [Result] Sources: 1
```

### Debugging Poor Answers

When an answer is incorrect or incomplete, check the logs:

1. **Query Analysis**: Did the agent understand the question correctly?
   - Wrong `query_type`? → Adjust instructions
   - Missing `primary_concepts`? → Add to prompt examples

2. **Search Plan**: Was the search strategy appropriate?
   - Wrong file? → Check game name translation
   - Poor search terms? → Add morphology patterns

3. **Primary Search**: Did it find relevant information?
   - `found: false`? → Check if PDF contains the info
   - Low `completeness_score`? → Verify follow-up logic

4. **Follow-up Searches**: Were they helpful?
   - `contributed_to_answer: false`? → Search was unnecessary
   - Missing critical concept? → Add to `potential_dependencies`

---

## Configuration

### Environment Variables

No new environment variables are required for SGR. The feature uses existing configuration:

```env
OPENAI_MODEL=gpt-4          # Model must support structured outputs
LOG_LEVEL=INFO              # Set to DEBUG for detailed reasoning logs
ADMIN_USER_IDS=123,456      # Admins always see verbose output
```

### Customizing Schemas

To modify the reasoning structure, edit `src/agent/schemas.py`:

```python
# Add a new field to track search duration
class SearchResultAnalysis(BaseModel):
    # ... existing fields ...
    search_duration_ms: Optional[int] = Field(
        default=None,
        description="Time taken to perform the search"
    )
```

Then update the agent instructions in `src/agent/definition.py` to populate the new field.

### Adjusting Completeness Thresholds

The agent uses `completeness_score` to decide on follow-ups. Adjust in instructions:

```python
# In definition.py instructions
"""
If `completeness_score` < 0.8 or `referenced_concepts` contains
unexplained terms, perform follow-up searches.
"""
```

Lower the threshold (e.g., 0.6) for fewer follow-ups, raise it (e.g., 0.9) for more thorough answers.

---

## Examples

### Example 1: Simple Query

**Input:** "What's the hand limit in Arkham Horror?"

**ReasonedAnswer:**
```json
{
  "query_analysis": {
    "query_type": "simple",
    "game_name": "Arkham Horror",
    "primary_concepts": ["hand limit"],
    "potential_dependencies": [],
    "reasoning": "Direct fact lookup, single concept"
  },
  "search_plan": {
    "search_terms": ["hand limit", "maximum cards"],
    "search_strategy": "exact_match"
  },
  "primary_search_result": {
    "found": true,
    "completeness_score": 0.95,
    "referenced_concepts": []
  },
  "follow_up_searches": [],
  "answer": "The hand limit in Arkham Horror is 8 cards.",
  "confidence": 0.95
}
```

### Example 2: Contextual Query (Russian)

**Input:** "Как двигаться в Gloomhaven?"

**ReasonedAnswer:**
```json
{
  "query_analysis": {
    "query_type": "contextual",
    "game_name": "Gloomhaven",
    "primary_concepts": ["movement"],
    "potential_dependencies": ["hexes", "obstacles", "jump"],
    "language_detected": "ru",
    "reasoning": "Movement rules may reference terrain types"
  },
  "search_plan": {
    "search_terms": ["движен|перемещ|ход|передвиж"],
    "search_strategy": "regex_morphology"
  },
  "primary_search_result": {
    "found": true,
    "completeness_score": 0.7,
    "referenced_concepts": ["препятствия", "прыжок"]
  },
  "follow_up_searches": [
    {
      "concept": "Obstacles",
      "why_needed": "Movement blocked by obstacles",
      "contributed_to_answer": true
    }
  ],
  "answer": "Движение в Gloomhaven:\n1. Потратьте очки движения\n2. Каждый гекс = 1 очко\n3. Препятствия блокируют движение...",
  "confidence": 0.85
}
```

### Example 3: Procedural Query

**Input:** "How does combat work in Root?"

**ReasonedAnswer:**
```json
{
  "query_analysis": {
    "query_type": "procedural",
    "game_name": "Root",
    "primary_concepts": ["combat", "battle"],
    "potential_dependencies": ["dice", "hits", "defenders", "attackers"],
    "reasoning": "Multi-step process requiring sequence explanation"
  },
  "search_plan": {
    "search_terms": ["combat", "battle", "fight"],
    "search_strategy": "exact_match"
  },
  "primary_search_result": {
    "found": true,
    "completeness_score": 0.6,
    "referenced_concepts": ["ambush", "defenseless"]
  },
  "follow_up_searches": [
    {
      "concept": "Ambush cards",
      "why_needed": "Combat can be modified by ambush",
      "contributed_to_answer": true
    }
  ],
  "answer": "Combat in Root:\n1. Attacker rolls 2 dice\n2. Higher die = attacker hits\n3. Lower die = defender hits\n4. Ambush cards can cancel hits...",
  "confidence": 0.9,
  "suggestions": ["How do ambush cards work?", "What is defenseless?"]
}
```

---

## Troubleshooting

### Issue: Agent Not Calling Tools

**Symptoms:**
- Logs show only one step with `MessageOutputItem`
- Agent returns `"found": false` without calling `list_directory_tree`, `search_filenames`, or `search_inside_file_ugrep`
- PDF file exists in storage but agent says it can't find it
- Log shows `"target_file": null` in search plan

**Example from logs:**
```
DEBUG:   Step: MessageOutputItem(agent=Agent(...))
INFO: [SGR] User 123456 - Reasoning Chain:
INFO:   [Plan] File: None, Strategy: broad_scan
INFO:   [Search] Found: False, Completeness: 0%
```

**Root Cause:**

The agent is using OpenAI's structured output feature (`output_type=ReasonedAnswer`), which combines:
1. A complex Pydantic schema (7 nested models, 30+ fields)
2. Tool calling requirements
3. Multi-step reasoning workflow

Some OpenAI models (especially small/fast ones) try to "predict" what tool results would be rather than actually calling the tools. They see the structured schema and think "I can fill this in without making tool calls."

**Solutions:**

### Solution 1: Enhanced Instructions (Implemented in v5)

The agent instructions now explicitly forbid predicting tool results:

```python
🚨 CRITICAL RULE: You MUST call tools to gather information. NEVER fill in
the schema with guessed or predicted values. If you haven't called tools yet,
DO NOT output the final ReasonedAnswer - call the tools first!

## MANDATORY TOOL CALLING WORKFLOW

**BEFORE outputting ReasonedAnswer, you MUST:**
1. Call `list_directory_tree()` to see available PDF files
2. Call `search_filenames(query)` to find the specific PDF
3. Call `search_inside_file_ugrep(filename, keywords)` to search the PDF
4. Only AFTER getting real tool results, output the ReasonedAnswer schema
```

### Solution 2: Use a More Capable Model

The SGR pattern requires a **capable model** to handle:
- Complex structured outputs (Pydantic models)
- Multi-step tool calling workflows
- Following detailed instructions

**Model Recommendations:**

| Model | Tool Calling | Structured Output | Speed | Cost | Recommendation |
|-------|--------------|-------------------|-------|------|----------------|
| `gpt-4o` | ✅ Excellent | ✅ Excellent | Fast | Medium | ✅ **Best choice** |
| `gpt-4o-mini` | ✅ Good | ✅ Good | Very Fast | Low | ✅ **Good balance** |
| `gpt-4-turbo` | ✅ Excellent | ✅ Excellent | Medium | High | ✅ Reliable |
| `gpt-4` | ✅ Very Good | ✅ Very Good | Slow | Very High | ⚠️ Expensive |
| `gpt-3.5-turbo` | ⚠️ Fair | ⚠️ Fair | Very Fast | Very Low | ❌ May skip tools |
| `gpt-5-nano` (proxy) | ❌ Poor | ❌ Poor | Fastest | Minimal | ❌ Unreliable |

**To change the model**, edit `.env`:
```bash
# Old (problematic)
OPENAI_MODEL=gpt-5-nano

# Recommended
OPENAI_MODEL=gpt-4o-mini  # Best balance of cost/performance
# OR
OPENAI_MODEL=gpt-4o       # Best performance
```

Then restart the bot:
```bash
just restart  # Docker
# OR
just run-local  # Local development
```

### Solution 3: Verify Tool Calls in Logs

Check that tools are actually being called:

```bash
# Should see tool invocations
grep -E "list_directory_tree|search_filenames|search_inside_file_ugrep" logs/bot.log

# Should see timing logs
grep "ScopeTimer" logs/bot.log
```

If you don't see tool calls but see responses, the model is predicting results.

### Solution 4: Alternative Architectures (Future)

If the issue persists even with a better model, consider:

**Option A: Two-Phase Approach**
1. Phase 1: Simple agent with tools (no structured output) - gathers data
2. Phase 2: Structured output agent - formats the response

**Option B: Simplified Schema**
- Reduce complexity of `ReasonedAnswer` schema
- Split into multiple simpler steps

**Option C: Forced Tool Calling**
- Use OpenAI's `tool_choice: "required"` parameter
- Force at least one tool call before output

---

## Conclusion

Schema-Guided Reasoning transforms RulesLawyerBot from a black-box question-answerer into a transparent reasoning system. Every answer comes with a complete audit trail showing:

1. **How the question was understood** (QueryAnalysis)
2. **What search strategy was chosen** (SearchPlan)
3. **What was found and whether it was complete** (SearchResultAnalysis)
4. **What additional context was gathered** (FollowUpSearch)
5. **How confident the agent is** (confidence score)

This enables debugging, quality control, and continuous improvement of the bot's capabilities.

**Important**: SGR with complex structured outputs requires a capable model. If you experience issues with tool calling, use `gpt-4o-mini` or better.

For questions or issues, check the logs or enable `/debug` mode to see the full reasoning chain.
