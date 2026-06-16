"""Server integration for HomeAITuber streaming mode.

Hooks the StreamingScheduler into the Open-LLM-VTuber server lifecycle.

Key design change from the old RadioServerIntegration:
- **No more separate radio pipeline.** The StreamingScheduler fires proactive
  ticks through process_single_conversation — the same function used for
  normal user chat. TTS, Live2D expressions, and lipsync all work
  automatically through the existing /client-ws.
- **Old /radio-ws is kept as a thin control channel** (start/stop streaming,
  set mood/language) but audio/segments no longer go through it.
- **Old RadioTickEngine + radio_tick.py are deprecated.**

Usage:
    from homeaituber.server_integration import StreamingIntegration

    # After creating the FastAPI server app:
    integration = StreamingIntegration()
    integration.set_ws_handler(server.ws_handler)
    integration.attach_to_app(server.app)

    # On server start:
    await integration.start()

    # On server shutdown:
    await integration.stop()
"""

import asyncio
import json
import logging as _logging
from pathlib import Path
from typing import Optional, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from loguru import logger


class StreamingIntegration:
    """Integrates the StreamingScheduler into the server lifecycle.

    Manages:
    - StreamingScheduler: background timer that fires proactive chat ticks
    - /radio-ws: thin control channel for mode/language/mood switching
      (audio and segments go through the main /client-ws, NOT here)
    - /api/feedback HTTP POST: alternative feedback submission
    - /api/state HTTP GET: current mode/language/engine status
    - Memory consolidation (kept from old architecture)
    """

    def __init__(
        self,
        soul_dir: str = "soul",
        interval_seconds: int = 600,
        consolidation_interval_minutes: int = 30,
        mood: str = "brisk",
        language: str = "en-jp",
    ):
        self.soul_dir = soul_dir
        self.interval_seconds = interval_seconds
        self.consolidation_interval_minutes = consolidation_interval_minutes
        self.mood = mood
        self.language = language

        self._ws_handler = None  # Set via set_ws_handler()
        self._scheduler = None

        self._radio_clients: Set[WebSocket] = set()
        self._task: Optional[asyncio.Task] = None

        # Defer memory worker import to avoid circular imports at module level
        self._memory_worker = None

    def set_ws_handler(self, ws_handler) -> None:
        """Set the WebSocketHandler reference after server initialization.

        The ws_handler provides access to:
        - client_contexts[client_uid] → ServiceContext (agent, TTS, Live2D)
        - client_connections[client_uid] → WebSocket (for sending TTS audio)
        - current_conversation_tasks[client_uid] → task tracking (for interrupts)
        """
        self._ws_handler = ws_handler

    def attach_to_app(self, app: FastAPI) -> None:
        """Register WebSocket and HTTP endpoints."""

        # ── HTTP feedback endpoint ──
        @app.post("/api/feedback")
        async def submit_feedback(data: dict):
            self._ensure_memory_worker()
            event = {
                "timestamp": data.get("timestamp", ""),
                "source": data.get("source", "web_ui"),
                "event": data.get("event", "comment"),
                "text": data.get("text", ""),
                "segment_id": data.get("segment_id", ""),
                "topic": data.get("topic", ""),
            }
            self._memory_worker.write_feedback(event)
            return {"status": "ok"}

        # ── HTTP state endpoint ──
        @app.get("/api/state")
        async def get_state():
            return {
                "mode": "streaming",
                "language": self.language,
                "scheduler_running": self.is_running,
            }

        # ── Control WebSocket (thin: just mode/language/mood control) ──
        @app.websocket("/radio-ws")
        async def radio_websocket(websocket: WebSocket):
            await websocket.accept()
            client_host = websocket.client.host if websocket.client else "unknown"
            logger.info(f"Control WebSocket client connected: {client_host}")
            self._radio_clients.add(websocket)

            # Send current state on connect
            await websocket.send_json({
                "type": "state-sync",
                "mode": "streaming",
                "language": self.language,
                "scheduler_running": self.is_running,
            })

            try:
                while True:
                    data = await websocket.receive_text()
                    msg = json.loads(data)
                    msg_type = msg.get("type", "")

                    if msg_type == "ping":
                        await websocket.send_json({"type": "pong"})

                    elif msg_type == "request-radio":
                        # Fire a streaming tick immediately (manual trigger)
                        if self._scheduler:
                            self._scheduler.mood = msg.get("mood", self.mood)
                            await self._scheduler.fire_immediately()
                        await websocket.send_json({"type": "request-ack"})

                    elif msg_type == "set-mode":
                        mode = msg.get("mode", "streaming")
                        if mode == "streaming":
                            if not self.is_running:
                                await self.start()
                            elif self._scheduler:
                                self._scheduler.resume()
                        elif mode == "idle":
                            if self._scheduler:
                                self._scheduler.pause()
                        await websocket.send_json({
                            "type": "mode-changed",
                            "mode": mode,
                        })
                        await self._broadcast_state()

                    elif msg_type == "set-language":
                        lang = msg.get("language", "en-jp")
                        from homeaituber.radio_prompt_builder import LANGUAGE_SCHEMAS
                        if lang not in LANGUAGE_SCHEMAS:
                            await websocket.send_json({
                                "type": "error",
                                "message": f"Invalid language: {lang}. Valid: {list(LANGUAGE_SCHEMAS.keys())}",
                            })
                            continue
                        self.language = lang
                        logger.info(f"Streaming language set to: {lang}")
                        await websocket.send_json({
                            "type": "language-changed",
                            "language": lang,
                        })
                        await self._broadcast_state()

                    elif msg_type == "set-mood":
                        mood = msg.get("mood", "brisk")
                        valid_moods = ("chaotic", "chill", "brisk", "thoughtful")
                        if mood not in valid_moods:
                            await websocket.send_json({
                                "type": "error",
                                "message": f"Invalid mood: {mood}. Valid: {valid_moods}",
                            })
                            continue
                        self.mood = mood
                        if self._scheduler:
                            self._scheduler.mood = mood
                        logger.info(f"Streaming mood set to: {mood}")
                        await websocket.send_json({
                            "type": "mood-changed",
                            "mood": mood,
                        })

                    elif msg_type in ("comment", "feedback"):
                        self._ensure_memory_worker()
                        event = {
                            "source": "radio_ws",
                            "event": msg_type,
                            "text": msg.get("text", ""),
                            "segment_id": msg.get("segment_id", ""),
                            "topic": msg.get("topic", ""),
                        }
                        self._memory_worker.write_feedback(event)
                        await websocket.send_json({"type": "feedback-ack"})

                    elif msg_type == "consolidate":
                        self._ensure_memory_worker()
                        result = await self._memory_worker.consolidate()
                        await websocket.send_json({
                            "type": "consolidation-result",
                            **result,
                        })

            except WebSocketDisconnect:
                logger.info(f"Control WebSocket client disconnected: {client_host}")
            except Exception as e:
                logger.error(f"Control WebSocket error: {e}")
            finally:
                self._radio_clients.discard(websocket)

        logger.info(
            "Streaming integration endpoints registered: /radio-ws (control), /api/feedback"
        )

    # ── Lifecycle ──

    async def start(self) -> None:
        """Create and start the streaming scheduler + consolidation."""
        if self._scheduler is not None:
            logger.warning("Streaming scheduler already started")
            return

        if not self._ws_handler:
            logger.warning("Streaming scheduler not started: no ws_handler set")
            return

        from homeaituber.radio_prompt_builder import RadioPromptBuilder
        from homeaituber.streaming_scheduler import StreamingScheduler

        prompt_builder = RadioPromptBuilder(Path(self.soul_dir))

        self._scheduler = StreamingScheduler(
            ws_handler=self._ws_handler,
            interval_seconds=self.interval_seconds,
            mood=self.mood,
            language_mode=self.language,
            prompt_builder=prompt_builder,
        )

        await self._scheduler.start()

        # Start periodic memory consolidation
        self._ensure_memory_worker()
        loop = asyncio.get_event_loop()
        self._consolidation_task = loop.create_task(
            self._consolidation_loop()
        )

        logger.info(
            f"Streaming integration started (interval={self.interval_seconds}s, "
            f"mood={self.mood}, lang={self.language}, "
            f"consolidation={self.consolidation_interval_minutes}min)"
        )

    async def stop(self) -> None:
        """Stop the scheduler, consolidation, and disconnect clients."""
        if self._scheduler:
            await self._scheduler.stop()
            self._scheduler = None

        if hasattr(self, "_consolidation_task") and self._consolidation_task:
            self._consolidation_task.cancel()
            try:
                await self._consolidation_task
            except asyncio.CancelledError:
                pass

        for ws in list(self._radio_clients):
            try:
                await ws.close()
            except Exception:
                pass
        self._radio_clients.clear()
        logger.info("Streaming integration stopped")

    @property
    def is_running(self) -> bool:
        return self._scheduler is not None and self._scheduler.is_running

    # ── Helpers ──

    def _ensure_memory_worker(self):
        """Lazy-init memory worker."""
        if self._memory_worker is None:
            from homeaituber.memory_worker import MemoryWorker
            self._memory_worker = MemoryWorker(self.soul_dir)

    async def _consolidation_loop(self) -> None:
        """Periodic memory consolidation."""
        interval_seconds = self.consolidation_interval_minutes * 60
        logger.info(
            f"Memory consolidation loop started (every {self.consolidation_interval_minutes} min)"
        )
        while True:
            try:
                await asyncio.sleep(interval_seconds)
                self._ensure_memory_worker()
                await self._memory_worker.consolidate()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Memory consolidation error: {e}")

    async def _broadcast_state(self) -> None:
        """Broadcast current state to all control WebSocket clients."""
        payload = {
            "type": "state-sync",
            "mode": "streaming",
            "language": self.language,
            "scheduler_running": self.is_running,
        }
        dead_clients: Set[WebSocket] = set()
        for ws in list(self._radio_clients):
            try:
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.send_json(payload)
            except Exception as e:
                logger.warning(f"Failed to broadcast state: {e}")
                dead_clients.add(ws)
        if dead_clients:
            self._radio_clients -= dead_clients
