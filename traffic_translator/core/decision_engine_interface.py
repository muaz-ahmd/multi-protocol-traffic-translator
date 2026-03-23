"""
Decision Engine Interface for Multi-Protocol Traffic Translator

Provides integration with cloud-based decision engines for AI-powered traffic control.
"""

import logging
import json
import time
from typing import Dict, Any, List, Optional, Callable
from abc import ABC, abstractmethod
from dataclasses import dataclass

from .message import TrafficMessage
from ..config.models import DecisionEngineConfig, DecisionEngineModel


@dataclass
class DecisionRequest:
    """Request sent to decision engine."""
    controller_id: str
    timestamp: float
    current_states: Dict[str, Any]
    detector_data: Dict[str, Any]
    pending_commands: List[Dict[str, Any]]
    context: Dict[str, Any]


@dataclass
class DecisionResponse:
    """Response from decision engine."""
    controller_id: str
    timestamp: float
    recommended_commands: List[Dict[str, Any]]
    confidence_score: float
    reasoning: str
    metadata: Dict[str, Any]


class DecisionEngineInterface(ABC):
    """
    Abstract interface for decision engine integration.

    Decision engines can be:
    - Cloud AI services (AWS SageMaker, Google AI Platform)
    - Local ML models
    - Rule-based systems
    - Human operators via API
    """

    @abstractmethod
    async def request_decision(self, request: DecisionRequest) -> DecisionResponse:
        """
        Request decision from the decision engine.

        Args:
            request: Decision request with current state

        Returns:
            Decision response with recommended actions
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if decision engine is available."""
        pass


class RESTDecisionEngine(DecisionEngineInterface):
    """
    REST API-based decision engine integration.
    """

    def __init__(self, config: DecisionEngineModel):
        """
        Initialize REST decision engine.

        Args:
            config: Configuration with API endpoints, auth, etc.
        """
        self.config = config
        self.logger = logging.getLogger(__name__)

        self.base_url = config.base_url
        self.api_key = config.api_key
        self.timeout = config.timeout

        # Initialize HTTP client (will be implemented)
        self._http_client = None

    async def request_decision(self, request: DecisionRequest) -> DecisionResponse:
        """Request decision via REST API."""
        # TODO: Implement HTTP request
        # For now, return mock response
        await self._mock_delay()

        return DecisionResponse(
            controller_id=request.controller_id,
            timestamp=time.time(),
            recommended_commands=[
                {
                    'phase_id': '1',
                    'command': 'green',
                    'duration': 45,
                    'priority': 0
                }
            ],
            confidence_score=0.85,
            reasoning="Standard timing based on traffic flow",
            metadata={'model_version': '1.0'}
        )

    async def _mock_delay(self):
        """Mock network delay."""
        import asyncio
        await asyncio.sleep(0.1)

    def is_available(self) -> bool:
        """Check API availability."""
        # TODO: Implement health check
        return True


class MQTTDecisionEngine(DecisionEngineInterface):
    """
    MQTT-based decision engine integration.
    """

    def __init__(self, config: DecisionEngineModel, mqtt_client):
        """
        Initialize MQTT decision engine.

        Args:
            config: MQTT configuration
            mqtt_client: MQTT client instance
        """
        self.config = config
        self.mqtt_client = mqtt_client
        self.logger = logging.getLogger(__name__)

        self.timeout = config.timeout

        # Response handling
        self._pending_requests: Dict[str, asyncio.Future] = {}
        self.mqtt_client.on_message = self._on_message

    async def request_decision(self, request: DecisionRequest) -> DecisionResponse:
        """Request decision via MQTT."""
        import asyncio
        import uuid

        request_id = str(uuid.uuid4())
        future = asyncio.Future()
        self._pending_requests[request_id] = future

        # Publish request
        payload = {
            'request_id': request_id,
            'data': {
                'controller_id': request.controller_id,
                'timestamp': request.timestamp,
                'current_states': request.current_states,
                'detector_data': request.detector_data,
                'pending_commands': request.pending_commands,
                'context': request.context
            }
        }

        self.mqtt_client.publish(
            self.request_topic,
            json.dumps(payload).encode('utf-8')
        )

        try:
            # Wait for response
            response_data = await asyncio.wait_for(future, timeout=self.timeout)
            return DecisionResponse(**response_data)
        except asyncio.TimeoutError:
            self.logger.error(f"Decision request timeout: {request_id}")
            raise
        finally:
            self._pending_requests.pop(request_id, None)

    def _on_message(self, client, userdata, msg):
        """Handle incoming MQTT messages."""
        try:
            payload = json.loads(msg.payload.decode('utf-8'))
            request_id = payload.get('request_id')

            if request_id in self._pending_requests:
                future = self._pending_requests[request_id]
                if not future.done():
                    future.set_result(payload['response'])

        except Exception as e:
            self.logger.error(f"Error processing decision response: {e}")

    def is_available(self) -> bool:
        """Check MQTT connection."""
        return self.mqtt_client.is_connected()


class LocalDecisionEngine(DecisionEngineInterface):
    """
    Local decision engine for rule-based or simple ML decisions.
    """

    def __init__(self, config: DecisionEngineModel):
        """
        Initialize local decision engine.

        Args:
            config: Configuration with rules or model path
        """
        self.config = config
        self.logger = logging.getLogger(__name__)

        # Simple rule-based decisions
        self.rules = config.rules or []

    async def request_decision(self, request: DecisionRequest) -> DecisionResponse:
        """Generate decision using local rules."""
        import asyncio
        await asyncio.sleep(0.05)  # Small delay to simulate processing

        # Simple rule: extend green time if traffic detected
        recommended_commands = []

        for phase_data in request.detector_data.get('phases', []):
            phase_id = phase_data['phase_id']
            vehicle_count = phase_data.get('vehicle_count', 0)

            if vehicle_count > 5:
                duration = 60  # Extend green
            else:
                duration = 30  # Normal green

            recommended_commands.append({
                'phase_id': phase_id,
                'command': 'green',
                'duration': duration,
                'priority': 0
            })

        return DecisionResponse(
            controller_id=request.controller_id,
            timestamp=time.time(),
            recommended_commands=recommended_commands,
            confidence_score=0.75,
            reasoning="Rule-based decision on vehicle count",
            metadata={'engine_type': 'local_rules'}
        )

    def is_available(self) -> bool:
        """Local engine is always available."""
        return True


class DecisionEngineManager:
    """
    Manages multiple decision engines with fallback logic.
    """

    def __init__(self, config: DecisionEngineConfig):
        """
        Initialize decision engine manager.

        Args:
            config: Configuration for decision engines
        """
        self.config = config
        self.logger = logging.getLogger(__name__)

        self.engines: Dict[str, DecisionEngineInterface] = {}
        self.fallback_order = config.fallback_order

        self._initialize_engines()

    def _initialize_engines(self):
        """Initialize configured decision engines."""
        engine_configs = self.config.engines

        for engine_name, engine_config in engine_configs.items():
            engine_type = engine_config.type

            if engine_type == 'rest':
                engine = RESTDecisionEngine(engine_config)
            elif engine_type == 'mqtt':
                # Would need MQTT client passed in
                continue
            elif engine_type == 'local':
                engine = LocalDecisionEngine(engine_config)
            else:
                self.logger.error(f"Unknown engine type: {engine_type}")
                continue

            self.engines[engine_name] = engine
            self.logger.info(f"Initialized decision engine: {engine_name}")

    async def get_decision(self, request: DecisionRequest) -> Optional[DecisionResponse]:
        """
        Get decision from available engines concurrently.

        Fires all available engines in parallel and returns the response
        with the highest confidence score. Falls back through results
        if some engines fail.

        Args:
            request: Decision request

        Returns:
            Decision response or None if no engine available
        """
        # Collect available engines in fallback order
        available = [
            (name, self.engines[name])
            for name in self.fallback_order
            if name in self.engines and self.engines[name].is_available()
        ]

        if not available:
            self.logger.warning("No decision engines available")
            return None

        # Fire all engines concurrently
        async def _safe_request(name: str, engine: DecisionEngineInterface):
            try:
                self.logger.debug(f"Requesting decision from {name}")
                return await engine.request_decision(request)
            except Exception as e:
                self.logger.error(f"Decision engine {name} failed: {e}")
                return None

        results = await asyncio.gather(
            *[_safe_request(name, engine) for name, engine in available]
        )

        # Pick the result with the highest confidence score
        best: Optional[DecisionResponse] = None
        for result in results:
            if result is not None:
                if best is None or result.confidence_score > best.confidence_score:
                    best = result

        if best is None:
            self.logger.warning("All decision engines failed")

        return best

    def get_available_engines(self) -> List[str]:
        """Get list of available engines."""
        return [
            name for name, engine in self.engines.items()
            if engine.is_available()
        ]