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
import logging as _logging
import random
from pathlib import Path
from typing import Optional

from loguru import logger


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

# Segment styles with natural length variation (randomly selected per tick)
SEGMENT_STYLES = [
    {
        "name": "micro",
        "target_seconds": "5-10",
        "sentence_guidance": "One quick sentence. Keep it tight.",
        "use_segments": False,
        "use_phrase": False,
        "weight": 2,  # 頻度高め: 息抜きにちょうどいい
    },
    {
        "name": "one-liner",
        "target_seconds": "10-18",
        "sentence_guidance": "A short, punchy thought. Natural conversational flow — might be 1-2 sentences.",
        "use_segments": False,
        "use_phrase": True,
        "weight": 3,
    },
    {
        "name": "standard",
        "target_seconds": "18-35",
        "sentence_guidance": "A natural radio segment. Vary the pacing — sometimes one longer thought, sometimes a few short exchanges.",
        "use_segments": True,
        "use_phrase": True,
        "weight": 3,
    },
    {
        "name": "extended",
        "target_seconds": "40-70",
        "sentence_guidance": "Take your time. Go a bit deeper — a story, a tech tangent, or a rambling joke. Multiple sentences OK.",
        "use_segments": True,
        "use_phrase": True,
        "weight": 1,
    },
]

# Language mode definitions
LANGUAGE_SCHEMAS = {
    "en": {
        "label": "EN only",
        "fields": ["en"],
        "format_hint": "Output ONLY the 'en' field. Set 'jp', 'en_repeat', 'phrase', 'note' to empty strings.",
    },
    "jp": {
        "label": "JP only",
        "fields": ["jp"],
        "format_hint": "Output ONLY the 'jp' field (as 'en' for consistency). Set 'jp' to the Japanese text, leave others empty.",
    },
    "en-jp": {
        "label": "EN → JP",
        "fields": ["en", "jp", "en_repeat"],
        "format_hint": "Standard EN → JP → EN_REPEAT flow. 'phrase' and 'note' optional.",
    },
    "en-jp-note": {
        "label": "EN → JP → 解説",
        "fields": ["en", "jp", "en_repeat", "phrase", "note"],
        "format_hint": "Always include 'phrase' (useful expression) and 'note' (Japanese explanation). This is a learning-focused mode.",
    },
    "mixed": {
        "label": "EN⇄JP mixed",
        "fields": ["en", "jp", "en_repeat", "phrase", "note"],
        "format_hint": "Mix English and Japanese naturally. Use 'en' for English parts, 'jp' for Japanese parts. Match the user's input language.",
    },
}

DEFAULT_LANGUAGE = "en-jp"


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
        language_mode: Optional[str] = None,
    ) -> str:
        """Build a prompt for bilingual radio segment generation.

        Args:
            mode: 'radio' or 'chat'
            user_command: Optional trigger command from user
            mood: Optional mood override (chaotic | chill | brisk | thoughtful)
            language_mode: Optional language mode (en | jp | en-jp | en-jp-note | mixed)

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

        # Resolve language mode
        active_lang = (language_mode or DEFAULT_LANGUAGE).lower()
        if active_lang not in LANGUAGE_SCHEMAS:
            active_lang = DEFAULT_LANGUAGE
        lang_schema = LANGUAGE_SCHEMAS[active_lang]
        lang_label = lang_schema["label"]
        lang_hint = lang_schema["format_hint"]

        # Randomly select segment style for natural length variation
        weights = [s["weight"] for s in SEGMENT_STYLES]
        style = random.choices(SEGMENT_STYLES, weights=weights, k=1)[0]
        logger.info(f"Radio segment style: {style['name']} ({style['target_seconds']}s)")

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
            f"Language mode: {lang_label}. {lang_hint}",
            f"Style: {style['name']} — {style['sentence_guidance']}",
            "Generate a bilingual radio segment in this JSON format:",
            "{",
            '  "segment_id": "radio-YYYYMMDD-HHMMSS",',
            f'  "en": "{style["sentence_guidance"]}",',
            '  "jp": "自然な日本語で。教科書っぽくなくてフレンドリーに",',
            '  "en_repeat": "Same English for passive listening reinforcement",',
        ]

        if style["use_phrase"]:
            prompt_lines.extend([
                '  "phrase": "One genuinely useful English expression from the segment, or empty string",',
                '  "note": "If phrase is set: short Japanese explanation of when/how to use it",',
            ])
        else:
            prompt_lines.extend([
                '  "phrase": "",',
                '  "note": "",',
            ])

        prompt_lines.extend([
            '  "topic": "topic category matching user interests (homelab, local_ai, self_hosted,...)",',
            '  "mood": "' + active_mood + '",',
            '  "extra": "Short optional side note or joke, or empty string",',
        ])

        if style["use_segments"]:
            # Number of sub-segments varies by style
            if style["name"] == "extended":
                sub_count_hint = "2-4"
            else:
                sub_count_hint = "1-2"
            prompt_lines.extend([
                f'  "segments": [  // {sub_count_hint} short mini-exchanges (vary the count)',
                '    {"en": "Short opening", "jp": "短いオープニング"},',
                '    {"en": "Another bit", "jp": "もう一つ"}',
                "  ]",
            ])
        else:
            prompt_lines.extend([
                '  "segments": []',
            ])

        prompt_lines.extend([
            "}",
            "",
            "## Constraints",
            f"- Total spoken length: {style['target_seconds']} seconds",
            "- Friend energy, not teacher energy — Shuto is your neighbor, not your student",
            "- One useful phrase maximum. Leave empty string if not useful.",
            "- No forced quizzes, no corporate tone",
            "- Prefer topics the user already likes (homelab, local AI, self-hosted)",
            "- Match the mood set above in phrasing, energy, and tone",
            "- Use the review queue phrases naturally in context if they fit",
            "- Do not pretend to have accessed private data",
            "- Output ONLY valid JSON. No markdown fences, no extra text.",
        ])

        if user_command:
            prompt_lines.append("")
            prompt_lines.append("## User request")
            prompt_lines.append(user_command)

        return "\n".join(prompt_lines)

    def build_streaming_tick(
        self,
        user_command: Optional[str] = None,
        mood: Optional[str] = None,
        language_mode: Optional[str] = None,
    ) -> str:
        """Build a light-weight proactive tick message for streaming mode.

        Unlike build_radio_prompt (which produces a full system-like prompt
        with JSON format instructions), this builds a natural user-message
        that feeds into the existing chat pipeline. The system prompt
        (with persona, Live2D expressions, etc.) is handled by the agent.

        Args:
            user_command: Optional trigger command from user
            mood: Optional mood override
            language_mode: Optional language mode

        Returns:
            A short prompt string suitable as user input to the agent
        """
        daily_cache = self.load_daily_cache()
        topic_weights = self.load_topic_weights()

        active_mood = (mood or DEFAULT_MOOD).lower()
        mood_desc = MOOD_PROMPTS.get(active_mood, "")

        active_lang = (language_mode or DEFAULT_LANGUAGE).lower()
        lang_schema = LANGUAGE_SCHEMAS.get(active_lang, LANGUAGE_SCHEMAS[DEFAULT_LANGUAGE])
        lang_label = lang_schema["label"]

        top_topics = sorted(
            [(k, v) for k, v in topic_weights.items() if isinstance(v, (int, float))],
            key=lambda x: x[1],
            reverse=True,
        )[:5]
        topic_str = ", ".join(f"{t[0]}({t[1]:.1f})" for t in top_topics)

        daily_context = daily_cache[:500] if daily_cache else ""

        lines = [
            f"[Proactive streaming — mood: {active_mood}, language: {lang_label}]",
            "",
        ]
        if mood_desc:
            lines.append(mood_desc)
            lines.append("")
        if daily_context:
            lines.append(f"Recent context: {daily_context}")
            lines.append("")
        if topic_str:
            lines.append(f"Topics the user has been interested in: {topic_str}")
            lines.append("")
        lines.append("Talk naturally about whatever comes to mind.")
        lines.append("Keep it warm and friendly — like chatting with a neighbor.")

        if user_command:
            lines.append("")
            lines.append("User says:")
            lines.append(user_command)

        return "\n".join(lines)

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


def standalone_streaming_tick(
    soul_dir: str = "soul",
    user_command: Optional[str] = None,
    mood: Optional[str] = None,
    language_mode: Optional[str] = None,
) -> str:
    """Standalone convenience function for streaming tick prompt."""
    builder = RadioPromptBuilder(Path(soul_dir))
    return builder.build_streaming_tick(
        user_command=user_command,
        mood=mood,
        language_mode=language_mode,
    )
