"""
HomeAITuber config loader.

Parses the homeaituber_config section from conf.yaml into HomeAITuberConfig.
Provides a convenience loader function used by run_server.py.
"""

import os
from pathlib import Path
from typing import Optional

import yaml
from loguru import logger
from pydantic import ValidationError

from .agent_profile import HomeAITuberConfig, AgentProfile, AgentType, StreamingConfig


def load_homeaituber_config(
    conf_path: str = "conf.yaml",
    env_override: Optional[str] = None,
) -> HomeAITuberConfig:
    """Load HomeAITuber config from conf.yaml.

    Args:
        conf_path: Path to conf.yaml
        env_override: Optional env var name that contains an alternative conf path

    Returns:
        Parsed HomeAITuberConfig with defaults for missing fields.

    The loading is intentionally lenient:
    - Missing homeaituber_config section → returns default (single main agent)
    - Invalid agent config → logs warning, skips that agent
    - Missing optional fields → filled with None (inherits from character_config at runtime)
    """
    path = conf_path
    if env_override and os.environ.get(env_override):
        path = os.environ[env_override]

    if not Path(path).exists():
        logger.warning(f"Config file not found: {path}. Using default HomeAITuberConfig.")
        return HomeAITuberConfig()

    try:
        with open(path) as f:
            raw = yaml.safe_load(f)
    except Exception as e:
        logger.warning(f"Failed to read config {path}: {e}. Using defaults.")
        return HomeAITuberConfig()

    raw_ha = raw.get("homeaituber_config", {}) if isinstance(raw, dict) else {}

    try:
        config = HomeAITuberConfig(**raw_ha)
    except ValidationError as e:
        logger.warning(f"Invalid homeaituber_config: {e}. Using defaults.")
        return HomeAITuberConfig()

    # Validate: at least one main agent
    if not config.main_agent:
        logger.warning(
            "No 'main' agent found in homeaituber_config. "
            "Adding default HomeAITuber main agent."
        )
        config.agents.insert(
            0,
            AgentProfile(name="HomeAITuber", type=AgentType.MAIN),
        )

    _log_config(config)
    return config


def _log_config(config: HomeAITuberConfig) -> None:
    """Log the loaded config at startup."""
    logger.info(f"HomeAITuber config loaded: {len(config.agents)} agent(s)")
    for a in config.agents:
        llm_info = f", llm={a.llm_model or 'default'}" if a.llm_model else ""
        tts_info = f", tts={a.tts_voice}" if a.tts_voice else ""
        l2d_info = f", live2d={a.live2d_model}" if a.live2d_model else ""
        logger.info(
            f"  [{a.type.value}] {a.name}{llm_info}{tts_info}{l2d_info}"
        )
    if config.topics:
        logger.info(f"  Topics ({len(config.topics)}): {', '.join(config.topics[:10])}")
    logger.info(
        f"  Streaming: {'enabled' if config.streaming.enabled else 'disabled'}, "
        f"interval={config.streaming.interval_seconds}s"
    )
