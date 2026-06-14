"""Memory worker for HomeAITuber.

Processes user comments/feedback and updates soul files in the background.

This is the "dream mode" — background memory consolidation that runs
outside the hot path. It reads feedback_log.jsonl, updates topic_weights,
user_profile, learning_state, and appends to dream_journal.jsonl.

Designed to be called:
- Periodically (e.g., every hour or on a cron schedule)
- On demand (user types /aituber dream)
- After a significant amount of feedback accumulates

The hot path (radio generation) must NOT depend on this module.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class MemoryWorker:
    """Background memory consolidation worker.

    Reads accumulated feedback/comments and updates soul files
    to make the next radio segments more personalized.
    """

    def __init__(self, soul_dir: str = "soul"):
        self.soul_dir = Path(soul_dir)
        self.soul_dir.mkdir(parents=True, exist_ok=True)

    # ── File helpers ──

    def _read_json(self, filename: str) -> dict:
        path = self.soul_dir / filename
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, Exception):
                return {}
        return {}

    def _write_json(self, filename: str, data: dict) -> None:
        path = self.soul_dir / filename
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _read_md(self, filename: str) -> str:
        path = self.soul_dir / filename
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    def _write_md(self, filename: str, content: str) -> None:
        path = self.soul_dir / filename
        path.write_text(content, encoding="utf-8")

    def _append_jsonl(self, filename: str, record: dict) -> None:
        path = self.soul_dir / filename
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # ── Feedback ingestion ──

    def read_feedback_log(self) -> list[dict]:
        """Read and clear the feedback_log.jsonl file."""
        path = self.soul_dir / "feedback_log.jsonl"
        entries = []
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                entries.append(json.loads(line))
                            except json.JSONDecodeError:
                                continue
            except Exception as e:
                logger.error(f"Failed to read feedback log: {e}")
        # Clear the file after reading
        path.write_text("", encoding="utf-8")
        return entries

    def write_feedback(self, event: dict) -> None:
        """Append a single feedback event to feedback_log.jsonl.

        Args:
            event: Dict with keys like:
                - timestamp: ISO-8601
                - source: "chat" | "mattermost" | "radio_ui"
                - event: "comment" | "like" | "skip" | "boring" | "save_phrase" | "topic_request"
                - text: str (the actual comment text or feedback note)
                - segment_id: optional
                - topic: optional
        """
        if "timestamp" not in event:
            event["timestamp"] = datetime.now(timezone.utc).isoformat()
        self._append_jsonl("feedback_log.jsonl", event)

    # ── Topic weights update ──

    def _extract_topics_from_text(self, text: str, existing_weights: dict) -> dict:
        """Simple keyword-based topic detection from user text.
        
        In Phase 2/3, this can be replaced with an LLM-based classifier.
        For now, uses simple substring matching.
        """
        text_lower = text.lower()
        boost = {}

        # Keywords mapped to topics
        topic_keywords = {
            "homelab": ["homelab", "home lab", "server", "cluster", "nas", "proxmox"],
            "local_ai": ["local ai", "local llm", "llama", "gemma", "atlas", "inference", "gguf"],
            "aituber": ["aituber", "vtuber", "vtube", "live2d", "avatar"],
            "self_hosted": ["self-host", "selfhost", "docker", "container", "k3s", "kubernetes"],
            "english_japanese_radio": ["english", "japanese", "radio", "bilingual", "en/ jp"],
            "weird_internet_culture": ["weird", "internet culture", "memes", "vibe"],
            "ai_humor": ["ai humor", "robot", "digital", "autonomous"],
            "language_learning": ["language", "learning", "phrase", "vocabulary", "grammar"],
            "open_source": ["open source", "github", "git", "oss", "foss"],
            "privacy_tech": ["privacy", "private", "wan", "lan-only", "local-first"],
            "k8s_cluster_management": ["k8s", "kubernetes", "pod", "deployment", "namespace"],
            "prompt_engineering": ["prompt", "persona", "system prompt"],
            "ambient_computing": ["ambient", "background", "passive", "radio"],
        }

        for topic, keywords in topic_keywords.items():
            if any(kw in text_lower for kw in keywords):
                boost[topic] = existing_weights.get(topic, 0.5) + 0.03

        return boost

    def update_topic_weights(self, feedback_entries: list[dict]) -> dict:
        """Update topic_weights.json based on recent feedback."""
        weights = self._read_json("topic_weights.json")

        now = datetime.now(timezone.utc).isoformat()
        decay_rate = 0.995  # Per-entry decay to prevent unbounded growth

        # Apply decay to all weights slightly
        for topic in weights:
            if topic != "updated_at" and isinstance(weights[topic], (int, float)):
                weights[topic] = max(0.01, weights[topic] * decay_rate)

        # Process each feedback entry
        for entry in feedback_entries:
            event_type = entry.get("event", "")
            text = entry.get("text", "")

            if event_type == "comment" and text:
                boosts = self._extract_topics_from_text(text, weights)
                for topic, boost in boosts.items():
                    weights[topic] = min(1.0, boost)

            elif event_type == "like":
                # Boost the segment's topic
                topic = entry.get("topic")
                if topic and topic in weights:
                    weights[topic] = min(1.0, weights[topic] + 0.05)

            elif event_type == "skip":
                # Slightly reduce the segment's topic
                topic = entry.get("topic")
                if topic and topic in weights:
                    weights[topic] = max(0.01, weights[topic] - 0.02)

            elif event_type == "boring":
                topic = entry.get("topic")
                if topic and topic in weights:
                    weights[topic] = max(0.01, weights[topic] - 0.05)

            elif event_type == "save_phrase":
                phrase = entry.get("text", "")
                if phrase:
                    self._append_to_review_queue(phrase)

        weights["updated_at"] = now
        self._write_json("topic_weights.json", weights)
        return weights

    # ── Review queue ──

    def _read_review_queue(self) -> list:
        path = self.soul_dir / "review_queue.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, Exception):
                return []
        return []

    def _write_review_queue(self, queue: list) -> None:
        path = self.soul_dir / "review_queue.json"
        path.write_text(
            json.dumps(queue, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _append_to_review_queue(self, phrase: str) -> None:
        """Add a phrase to the review queue (max 10 items)."""
        queue = self._read_review_queue()
        # Avoid duplicates
        if any(item.get("phrase") == phrase for item in queue):
            return
        queue.append({
            "phrase": phrase,
            "added_at": datetime.now(timezone.utc).isoformat(),
            "review_count": 0,
        })
        # Keep only the 10 most recent
        self._write_review_queue(queue[-10:])

    # ── Daily cache regeneration ──

    def regenerate_daily_cache(self, recent_feedback: list[dict]) -> str:
        """Regenerate daily_cache.md based on recent feedback context."""
        today = datetime.now().strftime("%Y-%m-%d")
        weights = self._read_json("topic_weights.json")
        profile = self._read_json("user_profile.json")

        # Find top topics
        sorted_topics = sorted(
            [(k, v) for k, v in weights.items() if k != "updated_at" and isinstance(v, (int, float))],
            key=lambda x: x[1],
            reverse=True,
        )
        top_topics = [t for t, _ in sorted_topics[:5] if t != "updated_at"]

        # Extract recent comments from feedback
        recent_comments = [
            e.get("text", "")
            for e in recent_feedback[-10:]
            if e.get("event") == "comment" and e.get("text")
        ]

        # Extract user likes from profile
        likes = profile.get("likes", [])

        cache = f"""# Daily Context
Generated: {today}

## Current Interests (topic weights)
{chr(10).join(f"- **{t}**: {weights.get(t, 0):.2f}" for t in top_topics)}

## Recent User Comments
{chr(10).join(f"- {c}" for c in recent_comments[-5:]) if recent_comments else "- (no recent comments yet)"}

## User Profile
- Name: {profile.get('user_name', 'User')}
- Likes: {', '.join(likes) if likes else '(not set)'}
- Dislikes: {', '.join(profile.get('dislikes', [])) if profile.get('dislikes') else '(not set)'}

## Mood
Default mood: brisk
"""

        self._write_md("daily_cache.md", cache)
        return cache

    # ── Dream journal ──

    def append_dream_journal(self, summary: str) -> None:
        """Append a dream journal entry."""
        entry = {
            "date": datetime.now(timezone.utc).isoformat(),
            "summary": summary,
        }
        self._append_jsonl("dream_journal.jsonl", entry)

    # ── Main consolidation ──

    async def consolidate(self) -> dict:
        """Run a full memory consolidation cycle.

        Returns a summary dict of what was updated.
        """
        logger.info("Memory worker: starting consolidation cycle")

        feedback = self.read_feedback_log()
        if not feedback:
            logger.info("Memory worker: no feedback to process")
            return {"status": "idle", "reason": "no_feedback"}

        # Update topic weights
        weights = self.update_topic_weights(feedback)
        n_topics_updated = len(weights) - 1  # Exclude "updated_at"

        # Update review queue
        for entry in feedback:
            if entry.get("event") == "save_phrase" and entry.get("text"):
                self._append_to_review_queue(entry["text"])

        # Regenerate daily cache
        daily_cache = self.regenerate_daily_cache(feedback)

        # Append dream journal
        comment_count = len([e for e in feedback if e.get("event") == "comment"])
        like_count = len([e for e in feedback if e.get("event") == "like"])
        summary = (
            f"Consolidated {len(feedback)} feedback entries "
            f"({comment_count} comments, {like_count} likes). "
            f"Updated {n_topics_updated} topic weights, regenerated daily cache."
        )
        self.append_dream_journal(summary)

        logger.info(f"Memory worker: {summary}")
        return {
            "status": "ok",
            "processed": len(feedback),
            "comments": comment_count,
            "likes": like_count,
            "topics_updated": n_topics_updated,
        }
