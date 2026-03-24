"""
State Aggregator for Multi-Protocol Traffic Translator

Aggregates state from commands, status updates, and feedback across multiple controllers.
Provides a single source of truth for the current state of the entire traffic system.
"""

import logging
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from .message import TrafficMessage


@dataclass
class ControllerState:
    """Aggregated state for a single traffic controller."""
    controller_id: str
    last_updated: float = field(default_factory=time.time)
    
    # Phase states: phase_id -> {command, duration, last_updated}
    phases: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    # Detector states: detector_id -> {status, last_updated}
    detectors: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    # Active faults: fault_code -> {message, last_updated}
    faults: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    # Metadata and stats
    metadata: Dict[str, Any] = field(default_factory=dict)
    command_count: int = 0
    error_count: int = 0


class StateAggregator:
    """
    Centralized state aggregator that maintains the latest state for all controllers.
    """

    def __init__(self, staleness_threshold: int = 300):
        """
        Initialize the state aggregator.
        
        Args:
            staleness_threshold: Seconds after which state is considered stale
        """
        self.controllers: Dict[str, ControllerState] = {}
        self.staleness_threshold = staleness_threshold
        self.logger = logging.getLogger(__name__)

    def update(self, message: TrafficMessage):
        """
        Update the aggregated state from a message.
        
        Args:
            message: The traffic message to process
        """
        controller_id = message.controller_id
        if not controller_id:
            return

        if controller_id not in self.controllers:
            self.controllers[controller_id] = ControllerState(controller_id=controller_id)

        state = self.controllers[controller_id]
        state.last_updated = time.time()

        if message.message_type == 'command':
            self._update_from_command(state, message)
        elif message.message_type == 'status':
            self._update_from_status(state, message)
        elif message.message_type == 'feedback':
            self._update_from_feedback(state, message)
        elif message.message_type == 'error':
            self._update_from_error(state, message)

    def _update_from_command(self, state: ControllerState, message: TrafficMessage):
        """Update phase state from an outgoing command."""
        if message.phase_id:
            state.phases[message.phase_id] = {
                'command': message.command,
                'duration': message.duration,
                'priority': message.priority,
                'last_updated': time.time()
            }
        state.command_count += 1

    def _update_from_status(self, state: ControllerState, message: TrafficMessage):
        """Update phase states from an incoming status message."""
        if message.phase_status:
            for phase_id, status in message.phase_status.items():
                # Don't overwrite more detailed command info if it's very recent
                # unless the status explicitly contradicts it
                if phase_id in state.phases:
                    existing = state.phases[phase_id]
                    if time.time() - existing['last_updated'] < 2:
                        continue
                
                state.phases[phase_id] = {
                    'command': status,
                    'last_updated': time.time()
                }
        
        if message.current_phase:
            state.metadata['current_active_phase'] = message.current_phase

    def _update_from_feedback(self, state: ControllerState, message: TrafficMessage):
        """Update detector states from feedback."""
        if message.detector_status:
            for detector_id, status in message.detector_status.items():
                state.detectors[detector_id] = {
                    'status': status,
                    'last_updated': time.time()
                }

    def _update_from_error(self, state: ControllerState, message: TrafficMessage):
        """Update fault state from an error message."""
        if message.error_code:
            state.faults[message.error_code] = {
                'message': message.error_message,
                'last_updated': time.time()
            }
        state.error_count += 1

    def get_controller_state(self, controller_id: str) -> Optional[ControllerState]:
        """Get the current aggregated state for a controller."""
        state = self.controllers.get(controller_id)
        if state and time.time() - state.last_updated > self.staleness_threshold:
            self.logger.warning(f"State for controller {controller_id} is stale")
            # We still return it, but maybe with a flag or filtered
        return state

    def get_all_states(self) -> Dict[str, ControllerState]:
        """Get states for all controllers."""
        return self.controllers

    def clear_stale_data(self, max_age: int = 3600):
        """Remove controllers that haven't been updated in a long time."""
        current_time = time.time()
        to_remove = [
            cid for cid, state in self.controllers.items()
            if current_time - state.last_updated > max_age
        ]
        for cid in to_remove:
            del self.controllers[cid]
            self.logger.info(f"Cleared stale state for controller {cid}")
