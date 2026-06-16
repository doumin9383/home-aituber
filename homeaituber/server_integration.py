"""
Server integration for HomeAITuber multi-agent streaming mode.

Hooks the MultiAgentScheduler into the Open-LLM-VTuber server lifecycle.

Design (v2 -- Director-based multi-agent):
- AgentProfile[] from ha_config define available agents (main, guest, director)
- Director decides topic & next speaker (when present)
- Main + Guest agents speak through the existing /client-ws pipeline
- Sub agents get their own ServiceContext (separate memory, same LLM pool)

Key changes from the old StreamingIntegration:
- No more individual init params (soul_dir, interval, mood, language) -- all in ha_config
- /radio-ws expanded: topic management commands + agent selection
- MultiAgentScheduler replaces StreamingScheduler
"""

import asyncio
import json
from pathlib import Path
from typing import Optional, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState
from loguru import logger

from homeaituber.agent_profile import (
    HomeAITuberConfig,
    AgentProfile,
    AgentType,
)


class StreamingIntegration:
    """Integrates multi-agent streaming into the Open-LLM-VTuber server.

    Manages:
    - MultiAgentScheduler: background timer that fires proactive chat ticks
    - /radio-ws: control channel for topics, agents, mode
    - /api/feedback: HTTP feedback submission
    - /api/state: current mode/agent/topic status
    - Memory consolidation
    """

    def __init__(
        self,
        ha_config: HomeAITuberConfig,
    ):
        self.ha_config = ha_config  # May be mutated at runtime (topics, interval)

        self._mood = "brisk"
        self._language = "en-jp"

        self._ws_handler = None  # Set via set_ws_handler()
        self._scheduler = None

        self._radio_clients: Set[WebSocket] = set()
        self._task: Optional[asyncio.Task] = None
        self._memory_worker = None

    @property
    def interval_seconds(self) -> int:
        return self.ha_config.streaming.interval_seconds

    @interval_seconds.setter
    def interval_seconds(self, value: int) -> None:
        self.ha_config.streaming.interval_seconds = value
        if self._scheduler:
            self._scheduler.interval_seconds = value

    @property
    def mood(self) -> str:
        return self._mood

    @mood.setter
    def mood(self, value: str) -> None:
        self._mood = value

    @property
    def language(self) -> str:
        return self._language

    @language.setter
    def language(self, value: str) -> None:
        self._language = value

    def set_ws_handler(self, ws_handler) -> None:
        """Set the WebSocketHandler reference after server initialization."""
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
                "agents": [
                    {"name": a.name, "type": a.type.value}
                    for a in self.ha_config.agents
                ],
                "topics": self.ha_config.topics,
                "interval": self.interval_seconds,
            }

        # ── Control WebSocket (thin: just control commands) ──
        @app.websocket("/radio-ws")
        async def radio_websocket(websocket: WebSocket):
            await websocket.accept()
            client_host = websocket.client.host if websocket.client else "unknown"
            logger.info(f"Control WebSocket client connected: {client_host}")
            self._radio_clients.add(websocket)
            await self._send_state_sync(websocket)

            try:
                while True:
                    data = await websocket.receive_text()
                    msg = json.loads(data)
                    msg_type = msg.get("type", "")

                    if msg_type == "ping":
                        await websocket.send_json({"type": "pong"})

                    elif msg_type == "request-radio":
                        if self._scheduler:
                            mood_override = msg.get("mood")
                            if mood_override:
                                self.mood = mood_override
                            topic_override = msg.get("topic")
                            speaker_override = msg.get("speaker")
                            await self._scheduler.fire_immediately(
                                topic_override=topic_override,
                                speaker_override=speaker_override,
                            )
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

                    elif msg_type == "set-interval":
                        seconds = msg.get("seconds", 600)
                        if seconds < 10:
                            seconds = 10
                        elif seconds > 3600:
                            seconds = 3600
                        self.interval_seconds = seconds
                        logger.info(f"Streaming interval set to: {seconds}s")
                        await websocket.send_json({
                            "type": "interval-changed",
                            "seconds": seconds,
                        })
                        await self._broadcast_state()

                    elif msg_type == "set-topic":
                        topic = msg.get("topic", "")
                        action = msg.get("action", "add")  # add / remove / list
                        if action == "add" and topic:
                            if topic not in self.ha_config.topics:
                                self.ha_config.topics.append(topic)
                            await websocket.send_json({
                                "type": "topic-changed",
                                "action": "add",
                                "topic": topic,
                                "topics": self.ha_config.topics,
                            })
                        elif action == "remove" and topic:
                            self.ha_config.topics = [
                                t for t in self.ha_config.topics if t != topic
                            ]
                            await websocket.send_json({
                                "type": "topic-changed",
                                "action": "remove",
                                "topic": topic,
                                "topics": self.ha_config.topics,
                            })
                        elif action == "list":
                            await websocket.send_json({
                                "type": "topic-list",
                                "topics": self.ha_config.topics,
                            })
                        await self._broadcast_state()

                    elif msg_type == "set-agents":
                        # Future: dynamic agent add/remove
                        pass

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
            "Streaming integration endpoints registered: /radio-ws (control), /api/feedback, /api/state"
        )

    # ── Lifecycle ──

    async def start(self) -> None:
        """Create and start the multi-agent streaming scheduler + consolidation."""
        if self._scheduler is not None:
            logger.warning("Streaming scheduler already started")
            return

        if not self._ws_handler:
            logger.warning("Streaming scheduler not started: no ws_handler set")
            return

        from homeaituber.radio_prompt_builder import RadioPromptBuilder
        from homeaituber.streaming_scheduler import MultiAgentScheduler

        prompt_builder = RadioPromptBuilder(Path(self.ha_config.soul_dir))

        self._scheduler = MultiAgentScheduler(
            ws_handler=self._ws_handler,
            ha_config=self.ha_config,
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
            f"Multi-agent streaming started: {len(self.ha_config.agents)} agent(s), "
            f"interval={self.interval_seconds}s"
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
        logger.info("Multi-agent streaming stopped")

    @property
    def is_running(self) -> bool:
        return self._scheduler is not None and self._scheduler.is_running

    # ── Helpers ──

    def _ensure_memory_worker(self):
        if self._memory_worker is None:
            from homeaituber.memory_worker import MemoryWorker
            self._memory_worker = MemoryWorker(self.ha_config.soul_dir)

    async def _consolidation_loop(self) -> None:
        interval_seconds = 30 * 60  # 30 min (fixed, not per-config)
        while True:
            try:
                await asyncio.sleep(interval_seconds)
                self._ensure_memory_worker()
                await self._memory_worker.consolidate()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Memory consolidation error: {e}")

    async def _send_state_sync(self, ws: WebSocket) -> None:
        """Send current state to a single client."""
        try:
            await ws.send_json({
                "type": "state-sync",
                "mode": "streaming",
                "language": self.language,
                "scheduler_running": self.is_running,
                "agents": [
                    {"name": a.name, "type": a.type.value}
                    for a in self.ha_config.agents
                ],
                "topics": self.ha_config.topics,
                "interval": self.interval_seconds,
            })
        except Exception as e:
            logger.warning(f"Failed to send state-sync: {e}")

    async def _broadcast_state(self) -> None:
        """Broadcast current state to all control WebSocket clients."""
        payload = {
            "type": "state-sync",
            "mode": "streaming",
            "language": self.language,
            "scheduler_running": self.is_running,
            "agents": [
                {"name": a.name, "type": a.type.value}
                for a in self.ha_config.agents
            ],
            "topics": self.ha_config.topics,
            "interval": self.interval_seconds,
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
