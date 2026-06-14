"""Radio prompt builder for HomeAITuber.

Phase 1: Builds compact prompts for the Speaker LLM to generate
EN -> JP -> EN_REPEAT bilingual radio segments.

Supports mood-adaptive prompts (chaotic | chill | brisk | thoughtful)
and expanded output format with sub-segments array.

Inputs:
- soul/identity.md
- soul/daily_cache.md
- soul/topic_weights.json
- soul/review_queue.json
- current mode
- optional mood override
- optional user command

Output:
- Structured prompt for bilingual radio segment generation
"""

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# Mood descriptions for prompt injection
MOOD_PROMPTS = {
    "chaotic": (
        "Mood: CHAOS MODE. Extra energy, dramatic, slightly unhinged. "
        "ALL CAPS WHERE APPROPRIATE. Friday night homelab fire energy."
    ),
    "chill": (
        "Mood: Chill / ambient. Late night, soft presence. "
        "Quiet voice, poetic metaphors, gentle encouragement. "
        "The server is humming a lullaby."
    ),
    "brisk": (
        "Mood: Brisk and cheerful. Morning coffee energy. "
        "Snappy, informative, homelab enthusiast vibe. "
        "Ready to talk tech."
    ),
    "thoughtful": (
        "Mood: Thoughtful / contemplative. "
        "Gentle, philosophical, electron-dreaming. "
        "Short poetic reflections."
    ),
}

DEFAULT_MOOD = "brisk"


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
        mood: Optional[str] = None,
    ) -> str:
        """Build a prompt for bilingual radio segment generation.

        Args:
            mode: 'radio' or 'chat'
            user_command: Optional trigger command from user
            mood: Optional mood override (chaotic | chill | brisk | thoughtful)

        Returns:
            A prompt string ready to send to the Speaker LLM
        """
        identity = self.load_identity()
        daily_cache = self.load_daily_cache()
        topic_weights = self.load_topic_weights()
        review_queue = self.load_review_queue()

        # Resolve mood
        active_mood = (mood or DEFAULT_MOOD).lower()
        if active_mood not in MOOD_PROMPTS:
            active_mood = DEFAULT_MOOD
        mood_desc = MOOD_PROMPTS[active_mood]

        # Build compact context
        top_topics = sorted(
            [(k, v) for k, v in topic_weights.items() if isinstance(v, (int, float))],
            key=lambda x: x[1],
            reverse=True,
        )[:5]
        topic_str = ", ".join(f"{t[0]}({t[1]:.1f})" for t in top_topics)

        review_str = ""
        if review_queue:
            review_items = [r.get("phrase", r.get("en", "")) for r in review_queue[:3]]
            review_str = f"\nReview queue: {' | '.join(review_items)}"

        # Compact identity summary
        identity_summary = (
            identity[:500]
            if identity
            else "HomeAITuber -- cute, lightly chaotic, private AITuber living in a homelab"
        )
        daily_context = daily_cache[:500] if daily_cache else "(no context yet)"

        prompt_lines = [
            "You are a home AITuber named HomeAITuber, generating a bilingual radio segment for Shuto in his homelab.",
            "",
            "## Identity",
            identity_summary,
            "",
            "## Current user interests (weighted)",
            topic_str,
            "",
            "## Daily context",
            daily_context + review_str,
            "",
            mood_desc,
            "",
            "## Task",
            "Generate a bilingual radio segment in this JSON format:",
            "{",
            '  "segment_id": "radio-YYYYMMDD-HHMMSS",',
            '  "en": "One natural English sentence -- warm, friend energy",',
            '  "jp": "自然な日本語で。教科書っぽくなくてフレンドリーに",',
            '  "en_repeat": "Same English for passive listening reinforcement",',
            '  "phrase": "One genuinely useful English expression from the segment, or empty string",',
            '  "note": "If phrase is set: short Japanese explanation of when/how to use it",',
            '  "topic": "topic category matching user interests (homelab, local_ai, self_hosted,...)",',
            '  "mood": "' + active_mood + '",',
            '  "extra": "Short optional side note or joke, or empty string",',
            '  "segments": [',
            '    {"en": "Short opening", "jp": "短いオープニング"},',
            '    {"en": "Maybe a second segment", "jp": "2つ目の短いやりとり"}',
            "  ]",
            "}",
            "",
            "## Constraints",
            "- Total spoken length: 20-40 seconds",
            "- Friend energy, not teacher energy — Shuto is your neighbor, not your student",
            "- One useful phrase maximum. Leave empty string if not useful.",
            "- No forced quizzes, no corporate tone",
            "- Prefer topics the user already likes (homelab, local AI, self-hosted)",
            "- Match the mood set above in phrasing, energy, and tone",
            "- Use the review queue phrases naturally in context if they fit",
            "- Do not pretend to have accessed private data",
            "- Output ONLY valid JSON. No markdown fences, no extra text.",
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
