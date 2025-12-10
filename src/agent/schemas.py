"""Pydantic schemas for Schema-Guided Reasoning (SGR).

This module defines structured output types that provide full transparency
into the agent's reasoning process. Each schema captures a specific step
in the reasoning chain, allowing complete auditability of how answers
are derived.

Usage:
    The agent uses these schemas to structure its thinking:
    1. QueryAnalysis - Understand what's being asked
    2. SearchPlan - Plan the search strategy
    3. SearchResultAnalysis - Analyze what was found
    4. FollowUpDecision - Decide if more info needed
    5. ReasonedAnswer - Final answer with full reasoning chain
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class QueryType(str, Enum):
    """Classification of user query complexity."""

    SIMPLE = "simple"
    """Direct fact lookup: 'What's the hand limit?'"""

    CONTEXTUAL = "contextual"
    """Needs related concepts: 'How do I attack?'"""

    PROCEDURAL = "procedural"
    """Multi-step process: 'How does a turn work?'"""

    CLARIFICATION = "clarification"
    """Ambiguous, needs user input: 'What about movement?'"""


class QueryAnalysis(BaseModel):
    """First step: Analyze and understand the user's question.

    This captures the agent's understanding of what information
    is being requested and what game concepts are involved.
    """

    original_question: str = Field(description="The user's original question verbatim")

    interpreted_question: str = Field(
        description="How the agent interprets the question (may clarify ambiguity)"
    )

    query_type: QueryType = Field(description="Classification of query complexity")

    game_name: Optional[str] = Field(
        default=None,
        description="Identified game name (English), or None if not specified",
    )

    primary_concepts: list[str] = Field(
        description="Main game concepts to search for (e.g., 'attack', 'movement')"
    )

    potential_dependencies: list[str] = Field(
        default_factory=list,
        description="Related concepts that might be needed for complete answer",
    )

    language_detected: str = Field(
        default="en", description="Detected language of the question (ISO 639-1 code)"
    )

    reasoning: str = Field(description="Why the agent classified the query this way")


class SearchPlan(BaseModel):
    """Plan for searching the rulebook.

    Captures the agent's strategy before executing searches.
    """

    target_file: Optional[str] = Field(
        default=None, description="Specific PDF file to search (if known)"
    )

    search_terms: list[str] = Field(description="Keywords/regex patterns to search for")

    search_strategy: str = Field(
        description="Approach: 'exact_match', 'regex_morphology', 'broad_scan'"
    )

    reasoning: str = Field(description="Why this search strategy was chosen")


class SearchResultAnalysis(BaseModel):
    """Analysis of search results.

    Evaluates what was found and whether it's sufficient.
    """

    search_term: str = Field(description="What was searched for")

    found: bool = Field(description="Whether any results were found")

    relevant_excerpts: list[str] = Field(
        default_factory=list, description="Key text snippets that answer the question"
    )

    page_references: list[str] = Field(
        default_factory=list, description="Page numbers or section references"
    )

    referenced_concepts: list[str] = Field(
        default_factory=list,
        description="Other game terms mentioned in the found text that may need lookup",
    )

    completeness_score: float = Field(
        ge=0,
        le=1,
        description="How complete is this answer? 0=incomplete, 1=fully answers question",
    )

    missing_context: list[str] = Field(
        default_factory=list,
        description="What additional information would make the answer more complete",
    )

    reasoning: str = Field(
        description="Analysis of search results quality and completeness"
    )


class FollowUpSearch(BaseModel):
    """Record of a follow-up search performed.

    Tracks additional searches done to gather context.
    """

    concept: str = Field(description="What concept was searched for")

    why_needed: str = Field(description="Why this follow-up was necessary")

    search_terms: list[str] = Field(description="Search terms used")

    found_info: str = Field(description="Summary of what was found")

    contributed_to_answer: bool = Field(
        description="Whether this info was useful for the final answer"
    )


class Source(BaseModel):
    """A source reference for the answer."""

    file: str = Field(description="PDF filename")

    location: str = Field(
        description="Page number, section, or description of where info was found"
    )

    excerpt: str = Field(description="Brief quote or paraphrase from source")


class ReasonedAnswer(BaseModel):
    """Final structured answer with complete reasoning chain.

    This is the main output_type for the agent. It contains both
    the answer AND the full chain of reasoning that led to it,
    providing complete transparency.
    """

    # === Reasoning Chain (for transparency) ===

    query_analysis: QueryAnalysis = Field(description="How the question was understood")

    search_plan: SearchPlan = Field(description="The search strategy used")

    primary_search_result: SearchResultAnalysis = Field(
        description="Results from the main search"
    )

    follow_up_searches: list[FollowUpSearch] = Field(
        default_factory=list,
        description="Additional searches performed for context (max 3)",
    )

    # === The Answer ===

    answer: str = Field(description="Clear, complete answer to the user's question")

    answer_language: str = Field(
        default="same_as_question",
        description="Language of the answer (should match question language)",
    )

    sources: list[Source] = Field(
        default_factory=list, description="References used to construct the answer"
    )

    # === Meta Information ===

    confidence: float = Field(
        ge=0, le=1, description="Confidence in answer correctness: 0=guess, 1=certain"
    )

    limitations: list[str] = Field(
        default_factory=list,
        description="Caveats, assumptions, or things user should verify",
    )

    suggestions: list[str] = Field(
        default_factory=list, description="Related questions user might want to ask"
    )
