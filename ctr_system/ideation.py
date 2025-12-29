#!/usr/bin/env python3
# ABOUTME: AI-powered title ideation engine for CTR optimization
# ABOUTME: Generates 10 variations using Claude CLI (uses existing Claude Code subscription)

import json
import re
import subprocess
from typing import List, Dict, Optional

from .config import (
    CLAUDE_MODEL,
    IDEAS_PER_PAGE,
    MAX_TITLE_LENGTH,
    IDEA_TYPES
)
from . import database as db


def call_claude_cli(prompt: str) -> str:
    """Call Claude CLI and return the response text"""
    try:
        result = subprocess.run(
            ['claude', '-p', prompt, '--output-format', 'json'],
            capture_output=True,
            text=True,
            timeout=120  # 2 minute timeout
        )

        if result.returncode != 0:
            raise RuntimeError(f"Claude CLI error: {result.stderr}")

        # Parse the JSON output to extract the response text
        output = json.loads(result.stdout)

        # The output format has a 'result' field with the response
        if isinstance(output, dict) and 'result' in output:
            return output['result']
        elif isinstance(output, str):
            return output
        else:
            # Try to find text in the response
            return str(output)

    except subprocess.TimeoutExpired:
        raise RuntimeError("Claude CLI timed out after 120 seconds")
    except json.JSONDecodeError:
        # If not valid JSON, return raw stdout
        return result.stdout
    except FileNotFoundError:
        raise RuntimeError("Claude CLI not found. Ensure 'claude' is in PATH.")


def generate_title_ideas(
    page_url: str,
    page_slug: str,
    current_title: str,
    current_ctr: float,
    expected_ctr: float,
    position: float,
    top_queries: List[Dict],
    experiment_history: List[Dict],
    past_ideas: List[str],
    idea_performance: List[Dict],
    review_id: Optional[int] = None
) -> List[Dict]:
    """Generate 10 title variations using Claude CLI"""

    # Format queries for prompt
    queries_text = "\n".join([
        f"  - \"{q['query']}\" ({q['impressions']:,} impressions, {q['ctr']*100:.1f}% CTR)"
        for q in top_queries[:10]
    ])

    # Format experiment history
    if experiment_history:
        history_text = "\n".join([
            f"  - {exp['new_title']} [{exp['idea_type']}] → {exp['outcome'] or 'pending'} ({exp.get('ctr_change_pct', 0):+.1f}%)"
            for exp in experiment_history[:5]
        ])
    else:
        history_text = "  No previous experiments"

    # Format past ideas to avoid
    avoid_text = "\n".join([f"  - {idea}" for idea in past_ideas[:20]]) if past_ideas else "  None"

    # Format idea type performance
    if idea_performance:
        perf_text = "\n".join([
            f"  - {p['idea_type']}: {p['success_rate']:.0f}% success rate ({p['total_experiments']} experiments)"
            for p in idea_performance
        ])
    else:
        perf_text = "  No data yet"

    # Format idea types for the prompt
    idea_types_text = "\n".join([
        f"  {i+1}. {it['type']}: {it['description']} (e.g., \"{it['example']}\")"
        for i, it in enumerate(IDEA_TYPES)
    ])

    prompt = f"""Generate exactly 10 SEO title variations for this underperforming page.

## Page Information
- URL: {page_url}
- Current Title: "{current_title}"
- Current CTR: {current_ctr*100:.2f}%
- Expected CTR at position {position:.1f}: {expected_ctr*100:.2f}%
- CTR Gap: -{(expected_ctr - current_ctr)*100:.2f}%

## Top Search Queries Driving Traffic
{queries_text}

## Past Experiments on This Page
{history_text}

## Ideas Already Tried (DO NOT REPEAT)
{avoid_text}

## Idea Type Performance on This Site
{perf_text}

## Required Idea Types (use one of each)
{idea_types_text}

## Requirements
1. Generate EXACTLY 10 titles, one for each idea type listed above
2. Each title MUST be under {MAX_TITLE_LENGTH} characters
3. Each title must be meaningfully different (not just word swaps)
4. DO NOT repeat any past ideas or experiments
5. Optimize for the top search queries
6. Consider what has worked well on this site (see performance data above)

## Output Format
Return a JSON array with exactly 10 objects, each with:
- "text": the title text (under {MAX_TITLE_LENGTH} chars)
- "type": the idea type (e.g., "specificity", "curiosity", etc.)
- "hypothesis": why this title should improve CTR (one sentence)
- "char_count": character count of the title

Example:
[
  {{"text": "7 Proven Ways to Find Your Life Purpose in 2025", "type": "specificity", "hypothesis": "Adding specific numbers and year increases perceived value and relevance", "char_count": 47}},
  ...
]

Return ONLY the JSON array, no other text."""

    response_text = call_claude_cli(prompt)

    # Extract JSON from response (handle potential markdown formatting)
    json_match = re.search(r'\[[\s\S]*\]', response_text)
    if json_match:
        ideas = json.loads(json_match.group())
    else:
        raise ValueError(f"Could not parse ideas from response: {response_text[:200]}")

    # Validate and clean ideas
    valid_ideas = []
    for idea in ideas:
        if len(idea['text']) <= MAX_TITLE_LENGTH:
            idea['char_count'] = len(idea['text'])
            valid_ideas.append(idea)

    # Store in database
    db.store_title_ideas(page_url, valid_ideas, review_id)

    return valid_ideas


def select_best_idea(
    ideas: List[Dict],
    idea_performance: List[Dict],
    experiment_history: List[Dict]
) -> Dict:
    """Automatically select the best title idea based on site learnings"""

    if not ideas:
        raise ValueError("No ideas to select from")

    # Build scoring based on idea type performance
    type_scores = {}
    for perf in idea_performance:
        # Score = success_rate weighted by sample size confidence
        confidence = min(perf['total_experiments'] / 10, 1.0)  # Max confidence at 10+ experiments
        type_scores[perf['idea_type']] = perf['success_rate'] * confidence

    # If no performance data, use equal scores
    if not type_scores:
        for idea_type in IDEA_TYPES:
            type_scores[idea_type['type']] = 50  # Default 50%

    # Score each idea
    scored_ideas = []
    for idea in ideas:
        score = type_scores.get(idea['type'], 50)

        # Bonus for idea types not recently tried on this page
        recent_types = [exp['idea_type'] for exp in experiment_history[:3]]
        if idea['type'] not in recent_types:
            score += 10  # Diversity bonus

        # Slight penalty for very long titles (might get truncated in SERP)
        if idea['char_count'] > 55:
            score -= 5

        scored_ideas.append({
            **idea,
            'score': score
        })

    # Sort by score and return best
    scored_ideas.sort(key=lambda x: x['score'], reverse=True)

    selected = scored_ideas[0]
    selected['selection_reason'] = f"Highest score ({selected['score']:.0f}) based on site performance data"

    return selected


def generate_and_select(
    page_url: str,
    page_slug: str,
    current_title: str,
    current_ctr: float,
    expected_ctr: float,
    position: float,
    top_queries: List[Dict],
    review_id: Optional[int] = None
) -> Dict:
    """Generate ideas and automatically select the best one"""

    # Get context
    history = db.get_experiment_history(page_url)
    past_ideas = [idea['idea_text'] for idea in db.get_past_ideas(page_url)]
    idea_performance = db.get_idea_type_performance()

    # Generate ideas
    ideas = generate_title_ideas(
        page_url=page_url,
        page_slug=page_slug,
        current_title=current_title,
        current_ctr=current_ctr,
        expected_ctr=expected_ctr,
        position=position,
        top_queries=top_queries,
        experiment_history=history,
        past_ideas=past_ideas,
        idea_performance=idea_performance,
        review_id=review_id
    )

    # Select best
    selected = select_best_idea(ideas, idea_performance, history)

    return {
        'all_ideas': ideas,
        'selected': selected,
        'selection_reason': selected.get('selection_reason', '')
    }
