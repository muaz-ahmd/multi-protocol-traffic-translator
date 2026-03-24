"""
Configuration Models for Traffic Translator using Pydantic
"""

from typing import Dict, Any, List, Optional
from pydantic import BaseModel, ConfigDict, Field

class AdapterModel(BaseModel):
    """Configuration for a protocol adapter."""
    type: str
    enabled: bool = True
    controller_id: str
    connection: Dict[str, Any] = Field(default_factory=dict)
    mapping: Dict[str, Any] = Field(default_factory=dict)
    polling_interval: float = 5.0
    timeout: float = 10.0

    @property
    def connection_params(self) -> Dict[str, Any]:
        """Alias for backward-compat with adapters that use connection_params."""
        return self.connection

class TranslationConfig(BaseModel):
    """Configuration for Translation Engine."""
    max_phase_duration: int = 300
    min_yellow_duration: int = 3
    preemption_enabled: bool = True
    history_size: int = 100
    default_durations: Dict[str, int] = Field(default_factory=lambda: {
        "green": 45,
        "yellow": 5,
        "red": 30,
        "flash": 10
    })
    conflicting_phases: Dict[str, List[str]] = Field(default_factory=dict)
    min_all_red_duration: int = 2
    transition_validation_enabled: bool = True

class DecisionEngineModel(BaseModel):
    """Configuration for a single decision engine."""
    type: str
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    timeout: float = 5.0
    rules: Optional[List[Dict[str, str]]] = None

class DecisionEngineConfig(BaseModel):
    """Configuration for Decision Engine Manager."""
    fallback_order: List[str] = Field(default_factory=list)
    engines: Dict[str, DecisionEngineModel] = Field(default_factory=dict)

class FeedbackSourceModel(BaseModel):
    """Configuration for a feedback source."""
    type: str
    host: str = 'localhost'
    port: Optional[int] = None
    community: Optional[str] = None
    unit_id: Optional[int] = None
    poll_interval: Optional[float] = None
    model_config = ConfigDict(extra='allow')

class FeedbackConfig(BaseModel):
    """Configuration for Feedback Manager."""
    sources: Dict[str, FeedbackSourceModel] = Field(default_factory=dict)

class LoggingConfig(BaseModel):
    """Configuration for Logging."""
    level: str = "INFO"
    format: str = "%(asctime)s %(name)s %(levelname)s: %(message)s"
    file: Optional[str] = None

class SystemConfig(BaseModel):
    """Configuration for General System."""
    max_concurrent_commands: int = 10
    command_timeout: int = 30
    health_check_interval: int = 60

class AppConfig(BaseModel):
    """Root Application Configuration."""
    translation: TranslationConfig = Field(default_factory=TranslationConfig)
    decision_engine: DecisionEngineConfig = Field(default_factory=DecisionEngineConfig)
    feedback: FeedbackConfig = Field(default_factory=FeedbackConfig)
    adapters: Dict[str, AdapterModel] = Field(default_factory=dict)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    system: SystemConfig = Field(default_factory=SystemConfig)
