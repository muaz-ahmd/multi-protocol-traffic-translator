"""
Universal Message Format for Multi-Protocol Traffic Translator

This module defines the standard MQTT message format that serves as the
interchange language between all protocol adapters in the traffic translator system.
"""

import json
import time
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict


@dataclass
class TrafficMessage:
    """
    Universal traffic control message format.

    All protocol adapters translate their native messages to/from this format.
    MQTT topics follow the pattern: traffic/{controller_id}/{message_type}/{phase_id}
    """

    # Message metadata
    timestamp: float
    controller_id: str
    message_type: str  # 'command', 'status', 'feedback', 'error'
    command_id: Optional[str] = None
    correlation_id: Optional[str] = None
    status: str = "PENDING"  # 'PENDING', 'SENT', 'ACK', 'EXECUTING', 'COMPLETED', 'FAILED', 'TIMEOUT'

    # Traffic control data
    phase_id: Optional[str] = None
    command: Optional[str] = None  # 'green', 'yellow', 'red', 'flash', 'preempt'
    duration: Optional[int] = None  # seconds
    priority: Optional[int] = None  # 0=normal, 1=high, 2=critical

    # Status information
    current_phase: Optional[str] = None
    phase_status: Optional[Dict[str, Any]] = None
    detector_status: Optional[Dict[str, Any]] = None

    # Error information
    error_code: Optional[str] = None
    error_message: Optional[str] = None

    # Protocol-specific data
    protocol_data: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        """Set default values if not provided."""
        if self.timestamp is None:
            self.timestamp = time.time()
        
        if self.message_type == 'command' and not self.command_id:
            import uuid
            self.command_id = str(uuid.uuid4())

    @classmethod
    def from_mqtt(cls, topic: str, payload: bytes) -> 'TrafficMessage':
        """
        Create TrafficMessage from MQTT topic and payload.

        Expected topic format: traffic/{controller_id}/{message_type}/{phase_id}
        Payload: JSON string
        """
        try:
            topic_parts = topic.split('/')
            if len(topic_parts) < 3 or topic_parts[0] != 'traffic':
                raise ValueError(f"Invalid topic format: {topic}")

            controller_id = topic_parts[1]
            message_type = topic_parts[2]
            phase_id = topic_parts[3] if len(topic_parts) > 3 else None

            data = json.loads(payload.decode('utf-8'))
            data['controller_id'] = controller_id
            data['message_type'] = message_type
            data['phase_id'] = phase_id

            return cls(**data)

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            raise ValueError(f"Failed to parse MQTT message: {e}")

    def to_mqtt(self) -> tuple[str, bytes]:
        """
        Convert to MQTT topic and payload.

        Returns: (topic, payload_bytes)
        """
        topic_parts = ['traffic', self.controller_id, self.message_type]
        if self.phase_id:
            topic_parts.append(self.phase_id)
        topic = '/'.join(topic_parts)

        # Create payload dict, excluding None values
        payload_dict = {k: v for k, v in asdict(self).items() if v is not None}
        payload = json.dumps(payload_dict).encode('utf-8')

        return topic, payload

    @classmethod
    def create_command(cls, controller_id: str, phase_id: str, command: str,
                      duration: Optional[int] = None, priority: int = 0,
                      command_id: Optional[str] = None) -> 'TrafficMessage':
        """Create a phase control command message."""
        return cls(
            timestamp=time.time(),
            controller_id=controller_id,
            message_type='command',
            command_id=command_id,
            phase_id=phase_id,
            command=command,
            duration=duration,
            priority=priority,
            status="PENDING"
        )

    @classmethod
    def create_status(cls, controller_id: str, current_phase: str,
                     phase_status: Dict[str, Any], correlation_id: Optional[str] = None) -> 'TrafficMessage':
        """Create a status update message."""
        return cls(
            timestamp=time.time(),
            controller_id=controller_id,
            message_type='status',
            correlation_id=correlation_id,
            current_phase=current_phase,
            phase_status=phase_status
        )

    @classmethod
    def create_feedback(cls, controller_id: str, phase_id: str,
                       detector_status: Dict[str, Any], correlation_id: Optional[str] = None) -> 'TrafficMessage':
        """Create a feedback message from detectors/sensors."""
        return cls(
            timestamp=time.time(),
            controller_id=controller_id,
            message_type='feedback',
            correlation_id=correlation_id,
            phase_id=phase_id,
            detector_status=detector_status
        )

    @classmethod
    def create_error(cls, controller_id: str, error_code: str,
                    error_message: str, correlation_id: Optional[str] = None) -> 'TrafficMessage':
        """Create an error message."""
        return cls(
            timestamp=time.time(),
            controller_id=controller_id,
            message_type='error',
            correlation_id=correlation_id,
            error_code=error_code,
            error_message=error_message
        )

    def is_expired(self, max_age_seconds: int = 300) -> bool:
        """Check if message is older than specified age."""
        return time.time() - self.timestamp > max_age_seconds

    def __str__(self) -> str:
        """String representation for logging."""
        return f"TrafficMessage(controller={self.controller_id}, type={self.message_type}, phase={self.phase_id}, command={self.command})"