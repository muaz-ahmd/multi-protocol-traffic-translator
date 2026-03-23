"""
Feedback Listener for Multi-Protocol Traffic Translator

Handles real-time feedback from traffic controllers via SNMP traps and Modbus polling.
"""

import logging
import asyncio
import time
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass
from abc import ABC, abstractmethod

from .message import TrafficMessage
from ..config.models import FeedbackConfig, FeedbackSourceModel


@dataclass
class FeedbackEvent:
    """Feedback event from a traffic controller."""
    controller_id: str
    timestamp: float
    event_type: str  # 'phase_change', 'detector_trigger', 'fault', 'status'
    phase_id: Optional[str] = None
    data: Dict[str, Any] = None


class FeedbackSource(ABC):
    """Abstract base class for feedback sources."""

    @abstractmethod
    async def start_listening(self, callback: Callable[[FeedbackEvent], None]):
        """Start listening for feedback events."""
        pass

    @abstractmethod
    async def stop_listening(self):
        """Stop listening for feedback events."""
        pass

    @abstractmethod
    def is_active(self) -> bool:
        """Check if feedback source is active."""
        pass


class SNMPFeedbackSource(FeedbackSource):
    """
    SNMP trap listener for NTCIP feedback.
    """

    def __init__(self, config: FeedbackSourceModel):
        """
        Initialize SNMP feedback source.

        Args:
            config: SNMP configuration
        """
        self.config = config
        self.logger = logging.getLogger(__name__)

        self.host = config.host
        self.port = config.port or 162
        self.community = config.community or 'public'

        self._active = False
        self._task: Optional[asyncio.Task] = None

        # NTCIP OID mappings
        self.ntcip_oids = {
            'phase_status': '1.3.6.1.4.1.1206.4.2.1.1.1',  # phaseStatus
            'detector_status': '1.3.6.1.4.1.1206.4.2.1.2.1',  # detectorStatus
            'fault_status': '1.3.6.1.4.1.1206.4.2.1.3.1',  # faultStatus
        }

    async def start_listening(self, callback: Callable[[FeedbackEvent], None]):
        """Start SNMP trap listening."""
        try:
            # TODO: Implement actual SNMP trap handling
            # For now, simulate periodic status checks
            self._active = True
            self._task = asyncio.create_task(self._simulate_traps(callback))
            self.logger.info(f"Started SNMP feedback listener for {self.host}:{self.port}")

        except Exception as e:
            self.logger.error(f"Failed to start SNMP listener: {e}")
            raise

    async def stop_listening(self):
        """Stop SNMP trap listening."""
        self._active = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.logger.info("Stopped SNMP feedback listener")

    async def _simulate_traps(self, callback: Callable[[FeedbackEvent], None]):
        """Simulate SNMP traps for development."""
        while self._active:
            try:
                # Simulate random feedback events
                import random
                if random.random() < 0.1:  # 10% chance every 5 seconds
                    event = FeedbackEvent(
                        controller_id=f"controller_{self.host}",
                        timestamp=time.time(),
                        event_type=random.choice(['phase_change', 'detector_trigger', 'status']),
                        phase_id=f"phase_{random.randint(1, 8)}",
                        data={
                            'phase_status': random.choice(['green', 'yellow', 'red']),
                            'vehicle_count': random.randint(0, 20)
                        }
                    )
                    callback(event)

                await asyncio.sleep(5)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in SNMP simulation: {e}")
                await asyncio.sleep(1)

    def is_active(self) -> bool:
        """Check if SNMP listener is active."""
        return self._active


class ModbusFeedbackSource(FeedbackSource):
    """
    Modbus polling for PLC feedback.
    """

    def __init__(self, config: FeedbackSourceModel):
        """
        Initialize Modbus feedback source.

        Args:
            config: Modbus configuration
        """
        self.config = config
        self.logger = logging.getLogger(__name__)

        self.host = config.host
        self.port = config.port or 502
        self.unit_id = config.unit_id or 1
        self.poll_interval = config.poll_interval or 2.0  # seconds

        self._active = False
        self._task: Optional[asyncio.Task] = None

        self.register_map = getattr(config, 'register_map', {
            'phase_status': {'address': 1000, 'count': 8},  # 8 phases
            'detector_data': {'address': 1100, 'count': 16},  # 16 detectors
            'fault_status': {'address': 1200, 'count': 4},   # 4 fault words
        })

    async def start_listening(self, callback: Callable[[FeedbackEvent], None]):
        """Start Modbus polling."""
        try:
            # TODO: Implement actual Modbus TCP client
            # For now, simulate polling
            self._active = True
            self._task = asyncio.create_task(self._poll_registers(callback))
            self.logger.info(f"Started Modbus feedback poller for {self.host}:{self.port}")

        except Exception as e:
            self.logger.error(f"Failed to start Modbus poller: {e}")
            raise

    async def stop_listening(self):
        """Stop Modbus polling."""
        self._active = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.logger.info("Stopped Modbus feedback poller")

    async def _poll_registers(self, callback: Callable[[FeedbackEvent], None]):
        """Poll Modbus registers periodically."""
        while self._active:
            try:
                # Simulate reading registers
                await self._simulate_register_read(callback)
                await asyncio.sleep(self.poll_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error polling Modbus registers: {e}")
                await asyncio.sleep(1)

    async def _simulate_register_read(self, callback: Callable[[FeedbackEvent], None]):
        """Simulate Modbus register reading."""
        import random

        # Simulate phase status (8 registers)
        phase_status = [random.randint(0, 3) for _ in range(8)]  # 0=red, 1=yellow, 2=green, 3=flash

        # Simulate detector data (16 registers)
        detector_data = [random.randint(0, 50) for _ in range(16)]  # vehicle counts

        # Simulate faults (4 registers)
        fault_status = [random.randint(0, 1) for _ in range(4)]  # 0=ok, 1=fault

        # Create feedback events
        controller_id = f"plc_{self.host}"

        # Phase status event
        phase_event = FeedbackEvent(
            controller_id=controller_id,
            timestamp=time.time(),
            event_type='phase_change',
            data={
                'phase_status': {
                    f'phase_{i+1}': ['red', 'yellow', 'green', 'flash'][status]
                    for i, status in enumerate(phase_status)
                }
            }
        )
        callback(phase_event)

        # Detector event
        detector_event = FeedbackEvent(
            controller_id=controller_id,
            timestamp=time.time(),
            event_type='detector_trigger',
            data={
                'detector_data': {
                    f'detector_{i+1}': count
                    for i, count in enumerate(detector_data)
                }
            }
        )
        callback(detector_event)

        # Fault event (only if faults exist)
        if any(fault_status):
            fault_event = FeedbackEvent(
                controller_id=controller_id,
                timestamp=time.time(),
                event_type='fault',
                data={
                    'fault_status': fault_status
                }
            )
            callback(fault_event)

    def is_active(self) -> bool:
        """Check if Modbus poller is active."""
        return self._active


class FeedbackListener:
    """
    Manages multiple feedback sources and converts events to TrafficMessages.
    """

    def __init__(self, config: FeedbackConfig):
        """
        Initialize feedback listener.

        Args:
            config: Configuration for feedback sources
        """
        self.config = config
        self.logger = logging.getLogger(__name__)

        self.sources: Dict[str, FeedbackSource] = {}
        self._message_callback: Optional[Callable[[TrafficMessage], None]] = None

        self._initialize_sources()

    def _initialize_sources(self):
        """Initialize configured feedback sources."""
        source_configs = self.config.sources

        for source_name, source_config in source_configs.items():
            source_type = source_config.type

            if source_type == 'snmp':
                source = SNMPFeedbackSource(source_config)
            elif source_type == 'modbus':
                source = ModbusFeedbackSource(source_config)
            else:
                self.logger.error(f"Unknown feedback source type: {source_type}")
                continue

            self.sources[source_name] = source
            self.logger.info(f"Initialized feedback source: {source_name}")

    def set_message_callback(self, callback: Callable[[TrafficMessage], None]):
        """
        Set callback for processed TrafficMessages.

        Args:
            callback: Function to call with converted messages
        """
        self._message_callback = callback

    async def start_all(self):
        """Start all feedback sources."""
        self.logger.info("Starting feedback listener...")

        for name, source in self.sources.items():
            try:
                await source.start_listening(self._on_feedback_event)
                self.logger.info(f"Started feedback source: {name}")
            except Exception as e:
                self.logger.error(f"Failed to start feedback source {name}: {e}")

    async def stop_all(self):
        """Stop all feedback sources."""
        self.logger.info("Stopping feedback listener...")

        stop_tasks = []
        for name, source in self.sources.items():
            if source.is_active():
                stop_tasks.append(source.stop_listening())

        if stop_tasks:
            await asyncio.gather(*stop_tasks, return_exceptions=True)

        self.logger.info("Feedback listener stopped")

    def _on_feedback_event(self, event: FeedbackEvent):
        """Handle feedback event and convert to TrafficMessage."""
        try:
            message = self._convert_event_to_message(event)

            if message and self._message_callback:
                self._message_callback(message)

        except Exception as e:
            self.logger.error(f"Error processing feedback event: {e}")

    def _convert_event_to_message(self, event: FeedbackEvent) -> Optional[TrafficMessage]:
        """Convert feedback event to TrafficMessage."""
        if event.event_type == 'phase_change':
            return TrafficMessage.create_status(
                controller_id=event.controller_id,
                current_phase=event.phase_id or 'unknown',
                phase_status=event.data or {}
            )

        elif event.event_type == 'detector_trigger':
            return TrafficMessage.create_feedback(
                controller_id=event.controller_id,
                phase_id=event.phase_id or 'all',
                detector_status=event.data or {}
            )

        elif event.event_type == 'fault':
            return TrafficMessage.create_error(
                controller_id=event.controller_id,
                error_code='controller_fault',
                error_message=f"Fault detected: {event.data}"
            )

        else:
            self.logger.warning(f"Unknown feedback event type: {event.event_type}")
            return None

    def get_active_sources(self) -> List[str]:
        """Get list of active feedback sources."""
        return [name for name, source in self.sources.items() if source.is_active()]

    async def health_check(self) -> Dict[str, bool]:
        """Check health of all feedback sources."""
        health = {}
        for name, source in self.sources.items():
            try:
                health[name] = source.is_active()
            except Exception as e:
                self.logger.error(f"Health check failed for {name}: {e}")
                health[name] = False
        return health