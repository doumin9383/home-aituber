"""Streaming conversation scheduler for HomeAITuber.

Replaces the old RadioTickEngine (separate LLM pipeline + separate TTS +
separate WebSocket) with a scheduler that fires proactive conversation
ticks THROUGH THE EXISTING CHAT PIPELINE (agent_engine.chat() →
process_agent_output → TTS → Live2D expressions → lipsync).

By riding on process_single_conversation (the same function used for normal
user chat), all Live2D expression parsing, TTS generation, lipsync, and
display-text sending work exactly as they do in chat mode — no duplicate
pipeline needed.

Design:
- Timer-based: fires a tick every `interval` seconds
- Each tick builds a natural text prompt (via RadioPromptBuilder)
  and sends it as a "user message" into the existing agent pipeline
- Interrupts handled naturally: user chat cancels the streaming task
  via the WebSocket handler's current_conversation_tasks dict
- After streaming task completes (or is cancelled), scheduler waits
  `interval` seconds before firing the next tick
- Uses skip_memory=False so the agent remembers previous ticks for continuity
- Uses skip_history=True to avoid polluting permanent chat_history files
- Client UID is resolved dynamically on each tick from connected clients
"""

import asyncio
from typing import Optional

from loguru import logger

from src.open_llm_vtuber.conversations.single_conversation import (
    process_single_conversation,
)


class StreamingScheduler:
    """Fires proactive conversation ticks on a timer through the existing
    chat pipeline (process_single_conversation).

    Key departure from the old RadioTickEngine:
    - No separate LLM client — uses the existing agent_engine
    - No separate TTS pipeline — uses the existing tts_engine + process_agent_output
    - No separate /radio-ws — audio goes through the main /client-ws
    - Live2D expression + lipsync work automatically (same as chat mode)
    - Chat history is maintained in agent memory for continuity
    """

    def __init__(
        self,
        ws_handler,  # WebSocketHandler instance
        interval_seconds: int = 600,
        mood: str = "brisk",
        language_mode: str = "en-jp",
        prompt_builder=None,  # RadioPromptBuilder instance
    ):
        self.ws_handler = ws_handler
        self.interval = interval_seconds
        self.mood = mood
        self.language_mode = language_mode
        self.prompt_builder = prompt_builder

        # Resolved dynamically on each tick
        self._client_uid: Optional[str] = None

        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._paused = False

    # ── Public API ──

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        """Start the streaming loop."""
        if self._task is not None and not self._task.done():
            logger.warning("Streaming scheduler already running")
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            f"Streaming scheduler started (interval={self.interval}s, "
            f"mood={self.mood}, language={self.language_mode})"
        )

    async def stop(self) -> None:
        """Stop the streaming loop."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Streaming scheduler stopped")

    def pause(self) -> None:
        """Temporarily pause streaming (e.g., when user starts chatting)."""
        self._paused = True

    def resume(self) -> None:
        """Resume streaming after pause."""
        self._paused = False

    async def fire_immediately(self) -> None:
        """Fire a tick immediately, outside the normal timer cycle."""
        await self._fire_tick()

    # ── Internal ──

    def _resolve_client_uid(self) -> Optional[str]:
        """Return the first connected client's UID, or the last known UID."""
        if self.ws_handler.client_connections:
            # Pick the first connected client
            uid = next(iter(self.ws_handler.client_connections.keys()))
            self._client_uid = uid
            return uid
        return self._client_uid

    def _get_context_and_ws(self):
        """Get (ServiceContext, websocket_send) for the current client, or (None, None)."""
        uid = self._resolve_client_uid()
        if not uid:
            return None, None

        context = self.ws_handler.client_contexts.get(uid)
        websocket = self.ws_handler.client_connections.get(uid)
        if not context or not websocket:
            return None, None

        return context, websocket.send_text

    async def _run_loop(self) -> None:
        """Main loop: tick → sleep → repeat."""
        while self._running:
            if self._paused:
                await asyncio.sleep(1)
                continue
            await self._fire_tick()
            await asyncio.sleep(self.interval)

    async def _fire_tick(self) -> None:
        """Execute one streaming tick:
        1. Check no conversation is already in progress
        2. Build a streaming prompt
        3. Fire process_single_conversation (same function as normal chat)
        4. Wait for completion or cancellation
        """
        uid = self._resolve_client_uid()
        if not uid:
            logger.debug("Streaming tick skipped: no connected client")
            return

        # Don't fire if a conversation is already in progress for this client
        existing = self.ws_handler.current_conversation_tasks.get(uid)
        if existing and not existing.done():
            logger.debug("Streaming tick skipped: conversation in progress")
            return

        context, websocket_send = self._get_context_and_ws()
        if not context or not websocket_send:
            logger.debug("Streaming tick skipped: no context/websocket for client")
            return

        # Build the streaming prompt (lightweight — personality handled by
        # system prompt in the agent, not re-injected here)
        if self.prompt_builder:
            user_input = self.prompt_builder.build_streaming_tick(
                mood=self.mood,
                language_mode=self.language_mode,
            )
        else:
            from homeaituber.radio_prompt_builder import standalone_streaming_tick
            user_input = standalone_streaming_tick(
                mood=self.mood,
                language_mode=self.language_mode,
            )

        logger.info(
            f"Streaming tick firing (uid={uid}, mood={self.mood}, lang={self.language_mode})"
        )

        metadata = {
            "proactive_speak": True,
            "skip_memory": False,   # Keep in agent memory for continuity
            "skip_history": True,   # Don't persist to chat_history files
        }

        # Fire through the exact same conversation pipeline used for normal chat
        task = asyncio.create_task(
            process_single_conversation(
                context=context,
                websocket_send=websocket_send,
                client_uid=uid,
                user_input=user_input,
                metadata=metadata,
            )
        )
        # Register so the WebSocket handler's interrupt mechanism can find
        # and cancel this task when the user starts chatting
        self.ws_handler.current_conversation_tasks[uid] = task

        try:
            await task
        except asyncio.CancelledError:
            logger.debug("Streaming tick cancelled (user interrupt)")
        except Exception as e:
            logger.error(f"Streaming tick failed: {e}")
        finally:
            # Only clean up if our task is still the registered one
            # (user chat may have overwritten it with a new task)
            if self.ws_handler.current_conversation_tasks.get(uid) is task:
                self.ws_handler.current_conversation_tasks.pop(uid, None)
