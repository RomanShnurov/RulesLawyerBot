# Multi-Stage Pipeline Architecture

This document explains how the multi-stage conversational pipeline is implemented in RulesLawyerBot to provide transparent, structured agent responses with game selection, clarification, and context-aware answers.

> **Status**: ✅ Implemented and Production-Ready (v0.2.0)
> **Last Updated**: 2025-12-25

## Table of Contents

1. [Overview](#overview)
2. [What is the Multi-Stage Pipeline?](#what-is-the-multi-stage-pipeline)
3. [Architecture](#architecture)
4. [Pydantic Schemas](#pydantic-schemas)
5. [Pipeline Flow](#pipeline-flow)
6. [Implementation Details](#implementation-details)
7. [User-Facing Features](#user-facing-features)
8. [Configuration](#configuration)
9. [Troubleshooting](#troubleshooting)

---

## Overview

RulesLawyerBot uses a multi-stage conversational pipeline that adapts based on user input and conversation state. The pipeline provides:

- **Interactive Game Selection**: Inline keyboard buttons when multiple games match
- **Clarification Flow**: Asks follow-up questions for ambiguous queries
- **Streaming Progress**: Real-time updates during searches
- **Context-Aware Responses**: Remembers current game across conversation turns
- **Structured Outputs**: Schema-guided responses with confidence scores

This enables:
- **Better UX**: Users can select games with buttons instead of typing
- **Smart Conversations**: Bot asks clarifying questions instead of guessing
- **Transparency**: Users see search progress in real-time
- **Accuracy**: Bot confirms understanding before searching

---

## What is the Multi-Stage Pipeline?

The multi-stage pipeline is a conversational flow that routes agent responses through different stages based on the current conversation state:

### Traditional Single-Stage Bot
```
User: "How to attack?"
Bot: [Guesses which game, searches, returns answer]
```

**Problems:**
- Bot might search the wrong game
- Ambiguous questions return poor answers
- No user feedback during long searches

### Multi-Stage Pipeline Bot
```
User: "How to attack?"
Bot: [Shows inline keyboard with matching games]
User: [Clicks "Super Fantasy Brawl"]
Bot: [Searches with progress updates]
Bot: [Returns complete answer with sources]
```

**Benefits:**
- Interactive game selection
- Clarification before searching
- Real-time progress feedback
- Context persists across questions

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        User Message                              │
│                  "How to attack in SFB?"                        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     OpenAI Agents SDK                            │
│                                                                  │
│  Agent(                                                          │
│    instructions = MULTI_STAGE_INSTRUCTIONS,                      │
│    tools = [search_filenames, search_inside_file_ugrep, ...],   │
│    output_type = PipelineOutput  ◄── Pydantic Schema            │
│  )                                                               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    PipelineOutput                                │
│                                                                  │
│  action_type: ActionType (discriminator)                        │
│  │                                                               │
│  ├─► CLARIFICATION_NEEDED                                       │
│  │    └─► clarification: ClarificationRequest                   │
│  │                                                               │
│  ├─► GAME_SELECTION                                             │
│  │    ├─► game_identification: GameIdentification               │
│  │    └─► clarification: ClarificationRequest                   │
│  │                                                               │
│  ├─► SEARCH_IN_PROGRESS                                         │
│  │    ├─► game_identification: GameIdentification               │
│  │    └─► search_progress: SearchProgress                       │
│  │                                                               │
│  └─► FINAL_ANSWER                                               │
│       ├─► game_identification: GameIdentification               │
│       └─► final_answer: FinalAnswer                             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                  Pipeline Handler                                │
│                  (src/pipeline/handler.py)                       │
│                                                                  │
│  handle_pipeline_output(output, update, context)                │
│  │                                                               │
│  ├─► CLARIFICATION_NEEDED                                       │
│  │    └─► Send text question to user                            │
│  │                                                               │
│  ├─► GAME_SELECTION                                             │
│  │    └─► Send inline keyboard with game buttons                │
│  │                                                               │
│  ├─► SEARCH_IN_PROGRESS                                         │
│  │    └─► Update progress message + ask question                │
│  │                                                               │
│  └─► FINAL_ANSWER                                               │
│       └─► Send formatted answer with sources                    │
└─────────────────────────────────────────────────────────────────┘
```

### File Structure

```
src/
├── agent/
│   ├── schemas.py         # Pydantic schemas (PipelineOutput, FinalAnswer, etc.)
│   ├── definition.py      # Agent with output_type=PipelineOutput
│   └── tools.py           # Search tools
├── pipeline/
│   ├── handler.py         # Routes PipelineOutput by ActionType
│   └── state.py           # Conversation state management
├── handlers/
│   ├── messages.py        # Message handler with streaming
│   ├── commands.py        # Command handlers (/start, /games)
│   └── callbacks.py       # Inline button handlers
└── utils/
    ├── progress_reporter.py  # Streaming progress updates
    ├── conversation_state.py # Per-user state tracking
    └── observability.py      # Langfuse tracing (optional)
```

---

## Pydantic Schemas

All schemas are defined in `src/agent/schemas.py`.

### ActionType (Enum)

Discriminator for pipeline routing:

```python
class ActionType(str, Enum):
    CLARIFICATION_NEEDED = "clarification_needed"
    GAME_SELECTION = "game_selection"
    SEARCH_IN_PROGRESS = "search_in_progress"
    FINAL_ANSWER = "final_answer"
```

### GameCandidate

A candidate game found during identification:

```python
class GameCandidate(BaseModel):
    english_name: str          # Game name in English
    pdf_filename: str          # PDF file name
    confidence: float          # 0-1 match confidence
```

### ClarificationRequest

Request for user clarification:

```python
class ClarificationRequest(BaseModel):
    question: str              # Question to ask (in user's language)
    options: list[str]         # Suggested options for inline buttons (max 5)
    context: str               # Why clarification is needed (for logging)
```

### GameIdentification

Result of game identification stage:

```python
class GameIdentification(BaseModel):
    identified_game: Optional[str]     # Identified game name (English)
    pdf_file: Optional[str]            # Located PDF filename
    candidates: list[GameCandidate]    # Multiple matching games
    from_session_context: bool         # True if inferred from session
```

### SearchProgress

Information about ongoing search:

```python
class SearchProgress(BaseModel):
    game_name: str                     # Game being searched
    pdf_file: str                      # PDF file being searched
    search_terms: list[str]            # Search terms used
    found_relevant: bool               # Whether relevant info was found
    needs_more_info: bool              # True if additional input needed
    additional_question: Optional[str] # Question to ask user
```

### FinalAnswer

Complete answer with metadata:

```python
class FinalAnswer(BaseModel):
    answer: str                        # Formatted answer text
    confidence: float                  # 0-1 confidence score
    limitations: list[str]             # Caveats or assumptions
    suggestions: list[str]             # Related questions
```

### PipelineOutput (Main Schema)

Unified output with discriminator:

```python
class PipelineOutput(BaseModel):
    # Discriminator - determines routing
    action_type: ActionType

    # Stage data (populated based on action_type)
    game_identification: Optional[GameIdentification]
    clarification: Optional[ClarificationRequest]
    search_progress: Optional[SearchProgress]
    final_answer: Optional[FinalAnswer]

    # Reasoning trace for debugging
    stage_reasoning: str
```

---

## Pipeline Flow

### Stage 1: Game Identification

**Trigger**: User sends a question

**Agent Decision**:
1. Check conversation state for current game context
2. Analyze question for game name mentions
3. Call `search_filenames()` to find matching PDFs
4. Determine action based on results

**Possible Actions**:
- **FINAL_ANSWER**: Game is known, proceed to search
- **GAME_SELECTION**: Multiple games match, show inline keyboard
- **CLARIFICATION_NEEDED**: Question is too vague

**Example (Multiple Matches)**:
```
User: "How to attack?"
Agent: PipelineOutput(
    action_type=GAME_SELECTION,
    game_identification=GameIdentification(
        candidates=[
            GameCandidate(english_name="Super Fantasy Brawl", confidence=0.8),
            GameCandidate(english_name="Gloomhaven", confidence=0.7)
        ]
    ),
    clarification=ClarificationRequest(
        question="Which game are you asking about?",
        options=["Super Fantasy Brawl", "Gloomhaven"]
    )
)
```

### Stage 2: Clarification

**Trigger**: `action_type = CLARIFICATION_NEEDED` or `GAME_SELECTION`

**Bot Action**:
- **CLARIFICATION_NEEDED**: Send text question
- **GAME_SELECTION**: Send inline keyboard with game buttons

**User Response**:
- Text answer or button click

**State Update**:
- Store selected game in conversation state
- Include game context in next agent call

### Stage 3: Search with Progress

**Trigger**: Game identified, searching rulebook

**Agent Decision**:
- Call `search_inside_file_ugrep()` with streaming
- May ask additional questions during search

**Bot Action**:
- Show progress message with fun updates
- Update message as search progresses
- If `needs_more_info = True`, ask follow-up question

**Example**:
```
Agent: PipelineOutput(
    action_type=SEARCH_IN_PROGRESS,
    search_progress=SearchProgress(
        game_name="Super Fantasy Brawl",
        search_terms=["атак", "удар"],
        found_relevant=True,
        needs_more_info=True,
        additional_question="Are you asking about melee or ranged attacks?"
    )
)
```

### Stage 4: Final Answer

**Trigger**: Search complete, answer ready

**Agent Output**:
```
Agent: PipelineOutput(
    action_type=FINAL_ANSWER,
    final_answer=FinalAnswer(
        answer="To attack in Super Fantasy Brawl:\n1. Spend 2 action points...",
        confidence=0.85,
        limitations=["Doesn't cover special character abilities"],
        suggestions=["How does defense work?"]
    )
)
```

**Bot Action**:
- Format answer with sources
- Show confidence indicator
- Display related questions
- Delete progress message

---

## Implementation Details

### Agent Definition (`src/agent/definition.py`)

```python
from src.agent.schemas import PipelineOutput

agent = Agent(
    name="Board Game Referee",
    model=model,
    instructions=MULTI_STAGE_INSTRUCTIONS,
    tools=[
        search_filenames,
        search_inside_file_ugrep,
        read_full_document
    ],
    output_type=PipelineOutput,  # Forces structured pipeline output
)
```

### Pipeline Handler (`src/pipeline/handler.py`)

```python
async def handle_pipeline_output(
    output: PipelineOutput,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    """Route pipeline output based on action_type."""

    if output.action_type == ActionType.GAME_SELECTION:
        # Build inline keyboard from candidates
        keyboard = build_game_selection_keyboard(
            output.game_identification.candidates
        )
        await update.message.reply_text(
            output.clarification.question,
            reply_markup=keyboard
        )

    elif output.action_type == ActionType.CLARIFICATION_NEEDED:
        # Send text question
        await update.message.reply_text(output.clarification.question)

    elif output.action_type == ActionType.SEARCH_IN_PROGRESS:
        # Update progress message
        await update_progress_message(output.search_progress)
        if output.search_progress.needs_more_info:
            await update.message.reply_text(
                output.search_progress.additional_question
            )

    elif output.action_type == ActionType.FINAL_ANSWER:
        # Format and send final answer
        text = format_final_answer(output.final_answer)
        await send_long_message(update.message, text)
```

### Conversation State (`src/pipeline/state.py`)

```python
def get_conversation_state(context: ContextTypes.DEFAULT_TYPE) -> dict:
    """Get per-user conversation state."""
    if "conversation_state" not in context.user_data:
        context.user_data["conversation_state"] = {
            "current_game": None,
            "game_context_set_at": None,
            "pending_clarification": None
        }
    return context.user_data["conversation_state"]
```

### Callback Handler (`src/handlers/callbacks.py`)

```python
async def handle_game_selection(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    """Handle game selection from inline keyboard."""
    query = update.callback_query
    game_name = query.data.replace("game:", "")

    # Update conversation state
    state = get_conversation_state(context)
    state["current_game"] = game_name
    state["game_context_set_at"] = datetime.now()

    # Acknowledge selection
    await query.answer()
    await query.edit_message_text(f"Selected: {game_name}")

    # Re-process original question with game context
    # ...
```

---

## User-Facing Features

### Inline Keyboard Buttons

When multiple games match, users see clickable buttons:

```
Bot: "Which game are you asking about?"

┌────────────────────────────┐
│  Super Fantasy Brawl       │
├────────────────────────────┤
│  Gloomhaven                │
├────────────────────────────┤
│  Arkham Horror             │
└────────────────────────────┘
```

### Streaming Progress Updates

During searches, users see real-time updates:

```
Bot: 🔍 Searching Super Fantasy Brawl rulebook...
Bot: 📖 Reading page 12...
Bot: ✅ Found relevant information!
```

Progress messages use fun thematic text from `src/utils/progress_reporter.py`.

### Confidence Indicators

Final answers show confidence level:

| Confidence | Indicator | Meaning |
|------------|-----------|---------|
| >= 80% | ✅ | High confidence |
| 50-79% | ⚠️ | Medium confidence |
| < 50% | ❓ | Low confidence |

### Game Context Persistence

Once a game is selected, it persists across questions:

```
User: "How to attack?"
Bot: [Shows game selection]
User: [Selects "Super Fantasy Brawl"]
Bot: [Returns answer about SFB]

User: "What about defense?"  # New question
Bot: [Automatically searches SFB, no re-selection needed]
```

---

## Configuration

### Environment Variables

No specific environment variables for the pipeline. Uses existing config:

```env
OPENAI_MODEL=gpt-4o-mini    # Model must support structured outputs
LOG_LEVEL=INFO              # Set to DEBUG for detailed pipeline logs
ADMIN_USER_IDS=123,456      # Admins see verbose reasoning
```

### Customizing Schemas

Edit `src/agent/schemas.py` to add fields:

```python
class FinalAnswer(BaseModel):
    answer: str
    confidence: float
    # Add new field
    search_duration_ms: Optional[int] = None
```

Update agent instructions in `src/agent/definition.py` to populate the field.

---

## Troubleshooting

### Issue: Agent Not Using Pipeline

**Symptom**: Agent returns plain text instead of structured `PipelineOutput`

**Solution**: Ensure model supports structured outputs:
```env
OPENAI_MODEL=gpt-4o-mini  # or gpt-4o
```

Small models (e.g., `gpt-3.5-turbo`) may not support complex structured outputs reliably.

### Issue: No Game Selection Shown

**Symptom**: Bot guesses game instead of showing buttons

**Check**:
1. Verify `search_filenames()` returns multiple candidates
2. Check logs for `action_type=GAME_SELECTION`
3. Ensure `build_game_selection_keyboard()` is called

### Issue: Progress Messages Not Updating

**Symptom**: No streaming progress during searches

**Check**:
1. Verify `ProgressReporter` is initialized in message handler
2. Check that agent is streaming (`Runner.run()` with streaming enabled)
3. Ensure Telegram API key has permission to edit messages

### Issue: Game Context Not Persisting

**Symptom**: Bot asks for game selection on every question

**Check**:
1. Verify conversation state is stored in `context.user_data`
2. Check `get_conversation_state()` is called before agent execution
3. Ensure game context is passed to agent in instructions/context

---

## Conclusion

The multi-stage pipeline architecture transforms RulesLawyerBot from a simple Q&A bot into an interactive conversational assistant that:

1. **Selects games interactively** with inline keyboard buttons
2. **Asks clarifying questions** when queries are ambiguous
3. **Shows search progress** in real-time with fun updates
4. **Remembers context** across conversation turns
5. **Provides structured answers** with confidence scores and sources

This architecture is implemented using:
- **Pydantic schemas** with `ActionType` discriminator for routing
- **Agent SDK structured outputs** (`output_type=PipelineOutput`)
- **Per-user conversation state** tracking current game context
- **Inline keyboards** for interactive game selection
- **Streaming progress** with thematic status messages

For implementation details, see the source files in `src/agent/`, `src/pipeline/`, and `src/handlers/`.

**Important**: The pipeline requires a capable model (`gpt-4o-mini` or better) for reliable structured output support.

For questions or issues, check logs or see [QUICKSTART.md](QUICKSTART.md) for troubleshooting.
