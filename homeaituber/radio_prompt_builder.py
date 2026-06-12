"""Radio prompt builder for HomeAITuber.

Phase 1: Builds compact prompts for the Speaker LLM to generate
EN -> JP -> EN_REPEAT radio segments.

Inputs:
- soul/identity.md
- soul/daily_cache.md
- soul/topic_weights.json
- soul/review_queue.json
- current mode
- optional user command

Output:
- Structured prompt + JSON schema for radio segment generation
"""

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class RadioPromptBuilder:
    """Builds compact prompts for proactive radio generation."""

    def __init__(self, soul_dir: Path):
        self.soul_dir = soul_dir

    def load_identity(self) -> str:
        """Read soul/identity.md."""
        path = self.soul_dir / "identity.md"
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    def load_daily_cache(self) -> str:
        """Read soul/daily_cache.md."""
        path = self.soul_dir / "daily_cache.md"
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    def load_topic_weights(self) -> dict:
        """Read soul/topic_weights.json."""
        path = self.soul_dir / "topic_weights.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return {}

    def load_review_queue(self) -> list:
        """Read soul/review_queue.json."""
        path = self.soul_dir / "review_queue.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return []

    def build_radio_prompt(
        self,
        mode: str = "radio",
        user_command: Optional[str] = None,
    ) -> str:
        """Build a compact prompt for radio segment generation.

        Args:
            mode: 'radio' or 'chat'
            user_command: Optional trigger command from user

        Returns:
            A prompt string ready to send to the Speaker LLM
        """
        identity = self.load_identity()
        daily_cache = self.load_daily_cache()
        topic_weights = self.load_topic_weights()
        review_queue = self.load_review_queue()

        # Build compact context
        top_topics = sorted(
            topic_weights.items(),
            key=lambda x: x[1],
            reverse=True,
        )[:5]
        topic_str = ", ".join(f"{t[0]}({t[1]:.1f})" for t in top_topics)

        review_str = ""
        if review_queue:
            review_items = [r.get("phrase", r.get("en", "")) for r in review_queue[:3]]
            review_str = f"\nReview queue: {' | '.join(review_items)}"

        identity_summary = (
            identity[:500]
            if identity
            else "HomeAITuber -- cute, lightly chaotic, private AITuber"
        )
        daily_context = daily_cache[:300] if daily_cache else "(no context yet)"

        prompt_lines = [
            "You are a private home AITuber generating a short bilingual radio segment.",
            "",
            "## Identity (summary)",
            identity_summary,
            "",
            "## Current user interests (weighted)",
            topic_str,
            "",
            "## Daily context",
            daily_context + review_str,
            "",
            "## Task",
            "Generate a radio segment in this JSON format:",
            "{",
            '  "segment_id": "radio-YYYYMMDD-HHMMSS",',
            '  "en": "One natural English sentence",',
            '  "jp": "Natural Japanese translation",',
            '  "en_repeat": "Same English sentence",',
            '  "phrase": "One useful English expression from the segment",',
            '  "note": "Short Japanese explanation of the phrase",',
            '  "topic": "topic category",',
            "  \"safety\": {",
            '    "uses_private_data": false,',
            '    "requires_external_access": false',
            "  }",
            "}",
            "",
            "## Constraints",
            "- Short enough for passive listening (15-30 seconds spoken)",
            "- One useful phrase maximum. Leave empty if not useful.",
            "- No textbook tone -- this is a friend, not a teacher",
            "- No forced quizzes",
            "- Prefer topics the user already likes",
            "- Do not pretend to have accessed private data",
            "- If the phrase is good, include a short Japanese explanation in 'note'",
        ]

        if user_command:
            prompt_lines.append("")
            prompt_lines.append("## User request")
            prompt_lines.append(user_command)

        return "\n".join(prompt_lines)

    def build_chat_prompt(
        self,
        user_message: str,
        persona_prompt: str = "",
    ) -> str:
        """Build a prompt for chat mode (direct user interaction)."""
        identity = self.load_identity()
        daily_cache = self.load_daily_cache()

        identity_summary = (
            identity[:400]
            if identity
            else "Cute, private, lightly chaotic AITuber"
        )
        daily_context = daily_cache[:200] if daily_cache else ""

        prompt_lines = []
        prompt_lines.append("You are HomeAITuber, a private home AITuber.")
        prompt_lines.append("")
        prompt_lines.append(identity_summary)
        if daily_context:
            prompt_lines.append("")
            prompt_lines.append(daily_context)
        if persona_prompt:
            prompt_lines.append("")
            prompt_lines.append(persona_prompt)
        prompt_lines.append("")
        prompt_lines.append(f"The user says: {user_message}")
        prompt_lines.append("")
        prompt_lines.append(
            "Respond naturally in a mix of English and Japanese as appropriate."
        )
        prompt_lines.append(
            "Keep it short, warm, and funny. No forced teaching. No corporate tone."
        )

        return "\n".join(prompt_lines)
