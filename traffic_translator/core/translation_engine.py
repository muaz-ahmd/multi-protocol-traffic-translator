"""
Translation Engine for Multi-Protocol Traffic Translator

Handles validation, conflict detection, mapping, and optimization of traffic control commands.
"""

import logging
import time
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass
from enum import Enum

from .message import TrafficMessage


class ValidationError(Exception):
    """Raised when message validation fails."""
    pass


class ConflictError(Exception):
    """Raised when command conflicts are detected."""
    pass


class CommandType(Enum):
    """Traffic signal command types."""
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"
    FLASH = "flash"
    PREEMPT = "preempt"
    HOLD = "hold"


@dataclass
class PhaseState:
    """Current state of a traffic phase."""
    phase_id: str
    current_command: str
    duration_remaining: int
    last_updated: float
    priority: int = 0


class TranslationEngine:
    """
    Core translation engine that validates, optimizes, and routes traffic commands.

    Features:
    - Command validation and conflict detection
    - Phase state tracking
    - Preemption handling
    - Optimization for safety and efficiency
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize translation engine.

        Args:
            config: Configuration dictionary with validation rules
        """
        self.config = config
        self.logger = logging.getLogger(__name__)

        # Phase state tracking
        self.phase_states: Dict[str, PhaseState] = {}

        # Validation rules
        self.max_phase_duration = config.get('max_phase_duration', 300)  # 5 minutes
        self.min_yellow_duration = config.get('min_yellow_duration', 3)   # 3 seconds
        self.preemption_enabled = config.get('preemption_enabled', True)

        # Conflict detection
        self.conflicting_phases = config.get('conflicting_phases', {})

        # Command history for optimization
        self.command_history: List[TrafficMessage] = []
        self.history_size = config.get('history_size', 100)

    def validate_message(self, message: TrafficMessage) -> bool:
        """
        Validate a traffic message for correctness and safety.

        Args:
            message: TrafficMessage to validate

        Returns:
            True if valid

        Raises:
            ValidationError: If message is invalid
        """
        # Basic validation
        if not message.controller_id:
            raise ValidationError("Controller ID is required")

        if message.message_type not in ['command', 'status', 'feedback', 'error']:
            raise ValidationError(f"Invalid message type: {message.message_type}")

        # Command-specific validation
        if message.message_type == 'command':
            self._validate_command(message)

        # Status-specific validation
        elif message.message_type == 'status':
            self._validate_status(message)

        return True

    def _validate_command(self, message: TrafficMessage):
        """Validate command message."""
        if not message.phase_id:
            raise ValidationError("Phase ID required for commands")

        if not message.command:
            raise ValidationError("Command required")

        try:
            command_type = CommandType(message.command.lower())
        except ValueError:
            raise ValidationError(f"Invalid command: {message.command}")

        # Duration validation
        if message.duration:
            if message.duration < 0:
                raise ValidationError("Duration cannot be negative")
            if message.duration > self.max_phase_duration:
                raise ValidationError(f"Duration exceeds maximum: {self.max_phase_duration}")

        # Yellow light minimum duration
        if command_type == CommandType.YELLOW and message.duration:
            if message.duration < self.min_yellow_duration:
                raise ValidationError(f"Yellow duration too short: {message.duration}")

        # Priority validation
        if message.priority is not None and (message.priority < 0 or message.priority > 2):
            raise ValidationError("Priority must be 0-2")

    def _validate_status(self, message: TrafficMessage):
        """Validate status message."""
        if not message.current_phase:
            raise ValidationError("Current phase required for status")

        if not message.phase_status:
            raise ValidationError("Phase status required")

    def detect_conflicts(self, message: TrafficMessage) -> List[str]:
        """
        Detect potential conflicts with existing commands.

        Args:
            message: New message to check

        Returns:
            List of conflict descriptions
        """
        conflicts = []

        if message.message_type != 'command':
            return conflicts

        phase_id = message.phase_id
        command = message.command.lower()

        # Check for conflicting phases
        # First, check if this phase conflicts with any active phases
        for active_phase_id, active_state in self.phase_states.items():
            if active_state.current_command in ['green', 'yellow', 'flash']:
                # Check if active_phase conflicts with target phase
                if active_phase_id in self.conflicting_phases:
                    if phase_id in self.conflicting_phases[active_phase_id]:
                        conflicts.append(
                            f"Phase {phase_id} conflicts with active phase {active_phase_id}"
                        )
                # Also check reverse conflicts
                if phase_id in self.conflicting_phases:
                    if active_phase_id in self.conflicting_phases[phase_id]:
                        conflicts.append(
                            f"Phase {phase_id} conflicts with active phase {active_phase_id}"
                        )

        # Check preemption conflicts
        if command == 'preempt' and not self.preemption_enabled:
            conflicts.append("Preemption is disabled")

        # Check for simultaneous conflicting commands
        active_commands = [
            state for state in self.phase_states.values()
            if state.current_command in ['green', 'yellow', 'flash']
        ]

        if len(active_commands) > 1:
            conflicts.append("Multiple phases active simultaneously")

        return conflicts

    def optimize_command(self, message: TrafficMessage) -> TrafficMessage:
        """
        Optimize command for efficiency and safety.

        Args:
            message: Command message to optimize

        Returns:
            Optimized message
        """
        if message.message_type != 'command':
            return message

        # Apply default durations if not specified
        if message.duration is None:
            defaults = self.config.get('default_durations', {})
            message.duration = defaults.get(message.command.lower(), 30)

        # Adjust priority based on command type
        if message.priority is None:
            priority_map = {
                'preempt': 2,
                'flash': 1,
                'green': 0,
                'yellow': 0,
                'red': 0
            }
            message.priority = priority_map.get(message.command.lower(), 0)

        # Optimize based on history
        self._apply_history_optimization(message)

        return message

    def _apply_history_optimization(self, message: TrafficMessage):
        """Apply optimizations based on command history."""
        # Skip optimization for preemption
        if message.command and message.command.lower() == 'preempt':
            return

        # Look for similar recent commands
        recent_commands = [
            cmd for cmd in self.command_history[-10:]  # Last 10 commands
            if cmd.phase_id == message.phase_id and
            time.time() - cmd.timestamp < 60  # Within last minute
        ]

        if recent_commands:
            # Avoid redundant commands
            last_command = recent_commands[-1]
            if (last_command.command == message.command and
                abs((last_command.duration or 0) - (message.duration or 0)) < 5):
                self.logger.info(f"Optimizing redundant command for phase {message.phase_id}")
                # Could extend duration instead of sending duplicate

    def update_phase_state(self, message: TrafficMessage):
        """
        Update internal phase state tracking.

        Args:
            message: Message to update state from
        """
        if message.message_type == 'command' and message.phase_id:
            self.phase_states[message.phase_id] = PhaseState(
                phase_id=message.phase_id,
                current_command=message.command or 'unknown',
                duration_remaining=message.duration or 0,
                last_updated=message.timestamp,
                priority=message.priority or 0
            )

        elif message.message_type == 'status' and message.current_phase:
            # Update from status messages
            if message.current_phase in self.phase_states:
                state = self.phase_states[message.current_phase]
                state.last_updated = message.timestamp

    def process_message(self, message: TrafficMessage) -> TrafficMessage:
        """
        Process a message through validation, conflict detection, and optimization.

        Args:
            message: Input message

        Returns:
            Processed message

        Raises:
            ValidationError: If validation fails
            ConflictError: If conflicts detected
        """
        # Validate message
        self.validate_message(message)

        # Check for conflicts
        conflicts = self.detect_conflicts(message)
        if conflicts:
            conflict_msg = "; ".join(conflicts)
            if message.priority and message.priority >= 2:
                self.logger.warning(f"Allowing conflicting command due to high priority: {conflict_msg}")
            else:
                raise ConflictError(f"Command conflicts detected: {conflict_msg}")

        # Optimize command
        optimized_message = self.optimize_command(message)

        # Update state
        self.update_phase_state(optimized_message)

        # Add to history
        self.command_history.append(optimized_message)
        if len(self.command_history) > self.history_size:
            self.command_history.pop(0)

        self.logger.debug(f"Processed message: {optimized_message}")
        return optimized_message

    def get_phase_states(self) -> Dict[str, Dict[str, Any]]:
        """Get current phase states for monitoring."""
        return {
            phase_id: {
                'command': state.current_command,
                'duration_remaining': state.duration_remaining,
                'last_updated': state.last_updated,
                'priority': state.priority
            }
            for phase_id, state in self.phase_states.items()
        }

    def cleanup_expired_states(self, max_age: int = 3600):
        """Remove expired phase states."""
        current_time = time.time()
        expired_phases = [
            phase_id for phase_id, state in self.phase_states.items()
            if current_time - state.last_updated > max_age
        ]

        for phase_id in expired_phases:
            del self.phase_states[phase_id]
            self.logger.info(f"Cleaned up expired phase state: {phase_id}")