"""
Multi-agent streaming scheduler for HomeAITuber.

Replaces the single-agent StreamingScheduler with a director-based
multi-agent architecture where:

- Director (optional) decides topic & next speaker
- Main + Guest agents speak through the existing chat pipeline
- Each speaking agent gets its own ServiceContext (separate memory)
- User input can be routed to the optimal agent via director

Director output format:
  JSON: {"speaker":"<name>","topic":"<topic|null>","direction":"<text>","mood":"<mood>"}
  Fallback: if JSON parse fails, extract "speaker" via regex and pass full text
"""

import asyncio
import json
import re
from pathlib import Path
from typing import Optional, Any

from loguru import logger

from homeaituber.agent_profile import (
    HomeAITuberConfig,
    AgentProfile,
    AgentType,
)


class DirectorDecision:
    """Parsed output from the director agent."""

    def __init__(self, raw_text: str):
        self.raw_text = raw_text
        self.speaker: str = "main"
        self.topic: Optional[str] = None
        self.direction: str = "Continue naturally"
        self.mood: str = "brisk"
        self._parse(raw_text)

    def _parse(self, text: str) -> None:
        # Try JSON extraction first
        json_data = None
        brace_match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if brace_match:
            try:
                json_data = json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                pass

        if json_data and isinstance(json_data, dict):
            self.speaker = (
                str(json_data.get("speaker", "main")).strip().lower()
            )
            self.topic = (
                str(json_data["topic"]).strip()
                if json_data.get("topic")
                and str(json_data["topic"]).strip().lower() != "null"
                else None
            )
            self.direction = str(
                json_data.get("direction", "Continue naturally")
            ).strip()
            self.mood = str(json_data.get("mood", "brisk")).strip()
        else:
            # Fallback: extract speaker from text via regex
            speaker_match = re.search(
                r'(?:speaker|話者|who|next|次)\s*[:\s]\s*(\w+)',
                text, re.IGNORECASE,
            ) or re.search(
                r'(?:let|have|ask)\s+(\w+)\s+(?:speak|talk|respond)',
                text, re.IGNORECASE,
            )
            if speaker_match:
                self.speaker = speaker_match.group(1).strip().lower()
            else:
                self.speaker = "main"

        # Validate mood
        valid_moods = ("brisk", "chill", "chaotic", "thoughtful")
        if self.mood not in valid_moods:
            self.mood = "brisk"


class MultiAgentScheduler:
    """Fires proactive conversation ticks through the existing chat pipeline,
    with optional director-based speaker/topic selection.

    Supports the single-agent mode (no director, no guests) as a subset:
    - No director -> falls back to round-robin on speaking agents
    - Only main agent -> falls back to original StreamingScheduler behaviour

    Agents are resolved by name from ha_config.agents.
    """

    def __init__(
        self,
        ws_handler,
        ha_config: HomeAITuberConfig,
        prompt_builder=None,
    ):
        self.ws_handler = ws_handler
        self.ha_config = ha_config
        self.prompt_builder = prompt_builder

        # Runtime mutable
        self.interval_seconds = ha_config.streaming.interval_seconds
        self.continuous_mode = ha_config.streaming.continuous_mode
        self.continuous_pause_seconds = ha_config.streaming.continuous_pause_seconds
        self.mood = "brisk"
        self.language = "en-jp"

        # Agent context cache: name -> ServiceContext-like dict
        self._agent_contexts: dict[str, Any] = {}

        # Internal state
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._paused = False
        self._client_uid: Optional[str] = None

        # Track recent agent turns for round-robin
        self._last_speaker: Optional[str] = None
        self._ticks_on_topic: int = 0
        self._current_topic: Optional[str] = None

    @property
    def is_running(self) -> bool:
        return self._running

    # ---- Lifecycle ----

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            logger.warning("MultiAgentScheduler already running")
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            f"MultiAgentScheduler started: {len(self.ha_config.speaking_agents)} speaker(s) "
            f"{' + director' if self.ha_config.director_agent else ''}"
        )

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("MultiAgentScheduler stopped")

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    async def fire_immediately(
        self,
        topic_override: Optional[str] = None,
        speaker_override: Optional[str] = None,
        mood_override: Optional[str] = None,
    ) -> None:
        """Fire a tick immediately, outside the normal timer cycle."""
        await self._fire_tick(
            topic_override=topic_override,
            speaker_override=speaker_override,
            mood_override=mood_override,
        )

    async def on_user_input(
        self,
        text: str,
    ) -> None:
        """Called when a user sends a chat message while streaming is active.

        If a director exists, ask it who should respond. Otherwise,
        route to the main agent (default behaviour).
        """
        if self.ha_config.director_agent:
            decision = await self._run_director(
                situation="user_input",
                user_input=text,
            )
            logger.debug(
                f"Director routed user input to '{decision.speaker}': "
                f"{decision.direction[:60]}"
            )
            await self._agent_speak(
                agent_name=decision.speaker,
                user_input=text,
                direction=decision.direction,
                topic=decision.topic,
                mood=decision.mood,
            )
        else:
            # Default: main agent handles it
            await self._agent_speak(
                agent_name="main",
                user_input=text,
                direction=None,
                topic=None,
                mood=self.mood,
            )

    # ---- Internal Loop ----

    async def _run_loop(self) -> None:
        """Main loop: tick -> (continuous: immediate, interval: sleep) -> repeat."""
        while self._running:
            if self._paused:
                await asyncio.sleep(1)
                continue
            await self._fire_tick()
            if self.continuous_mode:
                if self.continuous_pause_seconds > 0:
                    await asyncio.sleep(self.continuous_pause_seconds)
            else:
                await asyncio.sleep(self.interval_seconds)

    async def _fire_tick(
        self,
        topic_override: Optional[str] = None,
        speaker_override: Optional[str] = None,
        mood_override: Optional[str] = None,
    ) -> None:
        """Execute one streaming tick.

        1. If director exists -> ask director (topic + speaker + direction)
        2. If no director -> select next speaking agent + topic via round-robin
        3. Fire process_single_conversation for the chosen agent
        """
        uid = self._resolve_client_uid()
        if not uid:
            logger.debug("Streaming tick skipped: no connected client")
            return

        # Don't fire if conversation is in progress
        existing = self.ws_handler.current_conversation_tasks.get(uid)
        if existing and not existing.done():
            logger.debug("Streaming tick skipped: conversation in progress")
            return

        # ---- Director decides ----
        if self.ha_config.director_agent and not speaker_override:
            decision = await self._run_director(situation="timer")
            speaker_name = decision.speaker
            topic = decision.topic or self._current_topic
            direction = decision.direction
            mood = decision.mood

            if speaker_name not in [a.name.lower() for a in self.ha_config.agents]:
                logger.warning(
                    f"Director chose unknown agent '{speaker_name}', falling back to 'main'"
                )
                speaker_name = "main"

        # ---- No director: round-robin ----
        else:
            speakers = self.ha_config.speaking_agents
            if speaker_override:
                speaker_name = speaker_override
            elif self._last_speaker and len(speakers) > 1:
                # Pick the next speaker in rotation
                names = [a.name.lower() for a in speakers]
                try:
                    idx = names.index(self._last_speaker.lower())
                    speaker_name = names[(idx + 1) % len(names)]
                except ValueError:
                    speaker_name = speakers[0].name.lower()
            else:
                speaker_name = speakers[0].name.lower()

            topic = topic_override or self._current_topic
            direction = None
            mood = mood_override or self.mood

            # Topic rotation (if no override)
            if not topic_override and self.ha_config.topics:
                if self._ticks_on_topic >= 3 or not self._current_topic:
                    self._ticks_on_topic = 0
                    # Pick a random topic (avoid repeating the same one)
                    available = [
                        t for t in self.ha_config.topics
                        if t != self._current_topic
                    ] or self.ha_config.topics
                    self._current_topic = available[
                        hash(str(asyncio.get_event_loop().time()))
                        % len(available)
                    ]
                topic = self._current_topic
            self._ticks_on_topic += 1

        # ---- Fire the tick ----
        self._last_speaker = speaker_name
        await self._agent_speak(
            agent_name=speaker_name,
            user_input=None,
            direction=direction,
            topic=topic,
            mood=mood,
        )

    async def _agent_speak(
        self,
        agent_name: str,
        user_input: Optional[str] = None,
        direction: Optional[str] = None,
        topic: Optional[str] = None,
        mood: Optional[str] = None,
    ) -> None:
        """Make an agent speak through the chat pipeline."""
        uid = self._resolve_client_uid()
        if not uid:
            return

        context, websocket_send = self._get_context_and_ws(agent_name, uid)
        if not context or not websocket_send:
            logger.warning(f"Agent '{agent_name}': no context/websocket available")
            return

        # Build tick message
        if user_input:
            tick_message = user_input
        elif self.prompt_builder:
            tick_message = self.prompt_builder.build_streaming_tick(
                user_command=direction or None,
                mood=mood or None,
                language_mode=self.language,
            )
            if topic:
                tick_message += f"\n\n(Suggested topic: {topic})"
        else:
            tick_message = "Talk naturally."
            if topic:
                tick_message += f"\n(Suggested topic: {topic})"
            if direction:
                tick_message += f"\nDirection: {direction}"

        logger.info(
            f"Agent '{agent_name}' speaking: "
            f"{'user input' if user_input else 'tick'}"
            f"{f', topic={topic}' if topic else ''}"
            f"{f', mood={mood}' if mood else ''}"
        )

        metadata = {
            "proactive_speak": user_input is None,
            "skip_memory": False,
            "skip_history": True,
        }

        task = asyncio.create_task(
            self._run_conversation(
                context=context,
                websocket_send=websocket_send,
                client_uid=uid,
                user_input=tick_message,
                metadata=metadata,
            )
        )

        self.ws_handler.current_conversation_tasks[uid] = task
        try:
            await task
        except asyncio.CancelledError:
            logger.debug(f"Agent '{agent_name}' cancelled (user interrupt)")
        except Exception as e:
            logger.error(f"Agent '{agent_name}' failed: {e}")
        finally:
            if self.ws_handler.current_conversation_tasks.get(uid) is task:
                self.ws_handler.current_conversation_tasks.pop(uid, None)

    async def _run_conversation(
        self, context, websocket_send, client_uid, user_input, metadata
    ):
        """Run process_single_conversation."""
        from src.open_llm_vtuber.conversations.single_conversation import (
            process_single_conversation,
        )
        await process_single_conversation(
            context=context,
            websocket_send=websocket_send,
            client_uid=client_uid,
            user_input=user_input,
            metadata=metadata,
        )

    # ---- Director ----

    async def _run_director(
        self,
        situation: str = "timer",
        user_input: str = "",
    ) -> "DirectorDecision":
        """Ask the director agent for topic/speaker/direction decisions.

        Runs as a minimal LLM call -- short prompt, short output.
        """
        director = self.ha_config.director_agent
        if not director:
            return DirectorDecision(
                '{"speaker":"main","topic":null,"direction":"Continue naturally","mood":"brisk"}'
            )

        uid = self._resolve_client_uid()
        if not uid:
            return DirectorDecision(
                '{"speaker":"main","topic":null,"direction":"Continue naturally","mood":"brisk"}'
            )

        # Build director prompt
        topic_list = ", ".join(self.ha_config.topics) if self.ha_config.topics else "(empty)"
        agent_list = ", ".join(
            f"{a.name}({a.type.value})" for a in self.ha_config.agents
        )

        recent_summary = ""
        if self.prompt_builder:
            daily_cache = self.prompt_builder.load_daily_cache()
            recent_summary = daily_cache[:300] if daily_cache else ""

        user_input_line = f"User input: {user_input}" if user_input else "User input: (none)"

        director_prompt = f"""Situation: {situation}
Current topic: {self._current_topic or '(none)'}
Last speaker: {self._last_speaker or '(none)'}
Ticks on topic: {self._ticks_on_topic}
Topic list: {topic_list}
Agents: {agent_list}
{user_input_line}
Recent context: {recent_summary}

Output a JSON decision with speaker, topic (or null), direction (1 sentence), and mood."""

        # Get director's service context
        context = self._get_or_create_director_context(director, uid)
        if not context:
            return DirectorDecision(
                '{"speaker":"main","topic":null,"direction":"Continue naturally","mood":"brisk"}'
            )

        try:
            response = await context.agent_engine.chat(
                messages=[{"role": "user", "content": director_prompt}],
                stream=False,
            )
            raw_text = ""
            if isinstance(response, str):
                raw_text = response
            elif isinstance(response, dict):
                raw_text = response.get("content", str(response))
            elif response and hasattr(response, "content"):
                raw_text = response.content
            else:
                raw_text = str(response)

            logger.debug(f"Director raw output ({len(raw_text)} chars): {raw_text[:200]}")
            return DirectorDecision(raw_text)
        except Exception as e:
            logger.warning(f"Director agent failed: {e}")
            return DirectorDecision(
                '{"speaker":"main","topic":null,"direction":"Continue naturally","mood":"brisk"}'
            )

    def _get_or_create_director_context(self, director: AgentProfile, uid: str):
        """Create a minimal LLM-only context for the director agent.

        The director doesn't need TTS, ASR, VAD, or Live2D -- just an LLM.
        """
        cache_key = f"_director_{director.name}_{uid}"
        if cache_key in self._agent_contexts:
            return self._agent_contexts[cache_key]

        # Use the main client's context as a base
        base_context = self.ws_handler.client_contexts.get(uid)
        if not base_context:
            return None

        # For now, reuse the main agent's engine (same LLM)
        self._agent_contexts[cache_key] = base_context
        return base_context

    # ---- Helpers ----

    def _resolve_client_uid(self) -> Optional[str]:
        """Return the first connected client's UID, or the last known UID."""
        if self.ws_handler.client_connections:
            uid = next(iter(self.ws_handler.client_connections.keys()))
            self._client_uid = uid
            return uid
        return getattr(self, "_client_uid", None)

    def _get_context_and_ws(self, agent_name: str, uid: str):
        """Get (ServiceContext, websocket_send) for the given agent."""
        context = self.ws_handler.client_contexts.get(uid)
        websocket = self.ws_handler.client_connections.get(uid)
        if not context or not websocket:
            return None, None
        return context, websocket.send_text
