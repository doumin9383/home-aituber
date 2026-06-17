"""
Agent profile definitions for HomeAITuber multi-agent streaming.

Defines the data model for each streaming agent (main, guest, director)
and the HomeAITuberConfig that holds all agent profiles + topic list + streaming settings.

Design:
- AgentProfile is self-contained. All fields have defaults.
  null/Nones inherit from the main character config at runtime.
- Director is a subtype of guest with tts_voice=null and no Live2D.
- The config extends homeaituber_config in conf.yaml — parsed from raw YAML
  (Pydantic ignores extra fields in the upstream Config class).
"""

from typing import Optional
from pydantic import BaseModel, Field
from enum import Enum


class AgentType(str, Enum):
    """Role of an agent in the streaming system."""
    MAIN = "main"            # Primary character, always present, has Live2D + TTS
    GUEST = "guest"          # Secondary speaker, may or may not have Live2D
    DIRECTOR = "director"    # Does not speak. Decides topic & next speaker.


class AgentProfile(BaseModel):
    """Configuration profile for one streaming agent.

    At runtime, any null field inherits from the main character's config
    (defined in character_config in conf.yaml).
    """
    name: str = Field(..., description="Display name (e.g. 'HomeAITuber', 'Alice')")
    type: AgentType = Field(..., description="Role in the streaming system")

    # Persona & voice
    persona_prompt: Optional[str] = None
    tts_voice: Optional[str] = None

    # Live2D
    live2d_model: Optional[str] = None

    # LLM override — optional, allows using a different model or temperature
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    llm_base_url: Optional[str] = None
    llm_temperature: Optional[float] = None


class StreamingConfig(BaseModel):
    """Streaming-specific settings."""
    enabled: bool = True
    interval_seconds: int = 600
    continuous_mode: bool = False
    continuous_pause_seconds: float = 1.5


class HomeAITuberConfig(BaseModel):
    """Top-level config for HomeAITuber multi-agent streaming.

    Parsed from homeaituber_config section in conf.yaml.
    """
    agents: list[AgentProfile] = Field(
        default_factory=lambda: [
            AgentProfile(name="HomeAITuber", type=AgentType.MAIN),
        ],
        description="Agent profiles. At minimum, one 'main' agent required.",
    )
    topics: list[str] = Field(
        default_factory=list,
        description="Topic list for streaming. Empty = auto-generated from soul files.",
    )
    streaming: StreamingConfig = Field(
        default_factory=StreamingConfig,
        description="Streaming scheduler settings.",
    )
    soul_dir: str = Field(
        default="soul",
        description="Path to soul directory (identity, daily_cache, topic_weights).",
    )

    def get_agent(self, name: str) -> Optional[AgentProfile]:
        """Look up an agent profile by name."""
        for a in self.agents:
            if a.name == name:
                return a
        return None

    @property
    def main_agent(self) -> Optional[AgentProfile]:
        """Return the main agent profile."""
        for a in self.agents:
            if a.type == AgentType.MAIN:
                return a
        return None

    @property
    def director_agent(self) -> Optional[AgentProfile]:
        """Return the director agent profile, if any."""
        for a in self.agents:
            if a.type == AgentType.DIRECTOR:
                return a
        return None

    @property
    def guest_agents(self) -> list[AgentProfile]:
        """Return all guest (non-main, non-director) agents."""
        return [a for a in self.agents if a.type == AgentType.GUEST]

    @property
    def speaking_agents(self) -> list[AgentProfile]:
        """Return all agents that have TTS (main + guests)."""
        return [a for a in self.agents if a.type != AgentType.DIRECTOR]
