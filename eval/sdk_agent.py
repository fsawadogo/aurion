"""Aurion SDK Eval Agent — uses Claude Agent SDK for intelligent note evaluation.

This agent leverages Claude's reasoning to evaluate clinical note quality
beyond simple metrics — checking descriptive mode compliance, clinical
accuracy of section placement, and citation correctness.

Usage:
    python eval/sdk_agent.py "Evaluate the orthopedic note quality"
    python eval/sdk_agent.py "Compare all 3 providers on the same scenario"
    python eval/sdk_agent.py "Check descriptive mode compliance across recent sessions"

Requires: pip install claude-agent-sdk
"""

from __future__ import annotations

import asyncio
import sys

try:
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, AssistantMessage, query
    SDK_AVAILABLE = True
except ImportError:
    SDK_AVAILABLE = False


EVAL_SYSTEM_INSTRUCTIONS = """You are an Aurion Clinical AI eval agent. Your job is to evaluate
the quality of AI-generated clinical notes against strict criteria.

EVALUATION CRITERIA:
1. DESCRIPTIVE MODE: Notes must ONLY describe what was observed/said.
   Flag any interpretive, diagnostic, or suggestive statements.
   - BAD: "consistent with rotator cuff pathology"
   - GOOD: "demonstrated restricted internal rotation at approximately 20 degrees"

2. COMPLETENESS: All required template sections must be populated.
   Target: >= 90% of required sections have at least one claim.

3. CITATION TRACEABILITY: Every claim must reference a source segment.
   Target: >= 95% of claims have valid source_id.

4. HALLUCINATION: Claims must not reference non-existent transcript segments.
   Target: 0 hallucinations.

5. SECTION ACCURACY: Claims must be placed in the correct template section.

The backend API is at http://localhost:8080/api/v1/.
Auth: Bearer CLINICIAN

Available endpoints:
- POST /sessions (create session with specialty)
- POST /sessions/{id}/consent
- POST /sessions/{id}/start
- POST /sessions/{id}/stop
- GET /notes/{id}/stage1 (get note)
- GET /admin/metrics (pilot metrics)
- GET /admin/sessions (session list)

When evaluating, always:
1. Show the scoring rubric
2. Score each criterion with a number
3. List specific violations with quotes
4. Give an overall PASS/FAIL verdict
"""


async def run_sdk_agent(prompt: str) -> int:
    """Run the eval agent with Claude Agent SDK."""
    if not SDK_AVAILABLE:
        print("Claude Agent SDK not installed.")
        print("Install: pip install claude-agent-sdk")
        print("")
        print("Falling back to standalone eval agent...")
        print("Run: python eval/agent.py")
        return 1

    print("\n" + "=" * 60)
    print("AURION SDK EVAL AGENT")
    print("=" * 60)
    print(f"\nPrompt: {prompt}\n")

    session_id = None

    async for message in query(
        prompt=f"{EVAL_SYSTEM_INSTRUCTIONS}\n\nTask: {prompt}",
        options=ClaudeAgentOptions(
            allowed_tools=[
                "Bash",
                "Read",
                "Grep",
                "Glob",
                "WebFetch",
            ],
            max_turns=20,
            max_budget_usd=2.0,
            effort="high",
        ),
    ):
        if isinstance(message, AssistantMessage):
            # Print Claude's reasoning as it evaluates
            for block in message.content:
                if hasattr(block, "text"):
                    print(block.text)

        if isinstance(message, ResultMessage):
            session_id = message.session_id

            if message.subtype == "success":
                print(f"\n{'=' * 60}")
                print("EVAL COMPLETE")
                print(f"{'=' * 60}")
                print(message.result)
            elif message.subtype == "error_max_turns":
                print(f"\nHit turn limit. Resume: session {session_id}")
            elif message.subtype == "error_max_budget_usd":
                print("\nHit budget limit.")
            else:
                print(f"\nStopped: {message.subtype}")

            if message.total_cost_usd is not None:
                print(f"\nCost: ${message.total_cost_usd:.4f}")
                print(f"Turns: {message.num_turns}")

    return 0


async def main():
    if len(sys.argv) < 2:
        prompt = "Run Eval A: create an orthopedic session, walk through the full state machine, and report on pipeline health"
    else:
        prompt = " ".join(sys.argv[1:])

    return await run_sdk_agent(prompt)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
