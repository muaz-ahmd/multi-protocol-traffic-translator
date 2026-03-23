"""
Base Adapter for Multi-Protocol Traffic Translator

Abstract base class for all protocol adapters (NTCIP, Modbus, GPIO, REST, MQTT).
Includes a Circuit Breaker for resilient connection handling.
"""

import logging
import asyncio
import time
from enum import Enum
from typing import Dict, Any, List, Optional, Callable
from abc import ABC, abstractmethod

from ..core.message import TrafficMessage
from ..config.models import AdapterModel


class CircuitState(Enum):
    CLOSED = "closed"       # Normal operation
    OPEN = "open"           # Failing, fast-reject all calls
    HALF_OPEN = "half_open" # Allowing a single probe request


class CircuitBreaker:
    """
    Circuit Breaker pattern for adapter resilience.

    States:
        CLOSED  – Normal. Failures increment a counter.
        OPEN    – After `failure_threshold` consecutive failures, rejects
                  all calls immediately for `recovery_timeout` seconds.
        HALF_OPEN – After timeout expires, allows ONE probe call through.
                    Success → CLOSED, Failure → OPEN again.
    """

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 30.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0.0
        self._logger = logging.getLogger(f"{__name__}.CircuitBreaker")

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            # Check if recovery timeout has elapsed
            if time.monotonic() - self._last_failure_time >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
        return self._state

    def record_success(self):
        """Record a successful call and reset the breaker."""
        self._failure_count = 0
        self._state = CircuitState.CLOSED

    def record_failure(self):
        """Record a failed call and potentially trip the breaker."""
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
            self._logger.warning(
                f"Circuit OPEN after {self._failure_count} consecutive failures. "
                f"Will retry in {self.recovery_timeout}s."
            )

    def allow_request(self) -> bool:
        """Return True if a request is allowed through the breaker."""
        current = self.state
        if current == CircuitState.CLOSED:
            return True
        if current == CircuitState.HALF_OPEN:
            return True  # Allow one probe
        return False  # OPEN – fast-reject


class BaseAdapter(ABC):
    """
    Abstract base class for protocol adapters.

    All protocol adapters must implement this interface to ensure
    consistent behavior across different communication protocols.
    """

    def __init__(self, name: str, config: AdapterModel):
        """
        Initialize adapter.

        Args:
            name: Adapter identifier
            config: Adapter configuration
        """
        self.config = config
        self.name = name
        self.logger = logging.getLogger(f"{__name__}.{self.name}")

        self.controller_id = config.controller_id or self.name
        self.enabled = config.enabled

        # Message handling
        self._message_callback: Optional[Callable[[TrafficMessage], None]] = None

        # Connection state
        self._connected = False
        self._connecting = False

        # Circuit breaker for resilience
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=30.0
        )

        # Background tasks
        self._tasks: List[asyncio.Task] = []

    async def send_command_safe(self, message: TrafficMessage) -> bool:
        """
        Send a command through the circuit breaker.

        If the circuit is OPEN, the call is fast-rejected.
        On success the breaker resets; on failure, the count increments.
        """
        if not self._circuit_breaker.allow_request():
            self.logger.warning(
                f"Circuit breaker OPEN for {self.name} – rejecting command"
            )
            return False

        try:
            result = await self.send_command(message)
            if result:
                self._circuit_breaker.record_success()
            else:
                self._circuit_breaker.record_failure()
            return result
        except Exception as e:
            self._circuit_breaker.record_failure()
            self.logger.error(f"Command failed through circuit breaker: {e}")
            return False

    def set_message_callback(self, callback: Callable[[TrafficMessage], None]):
        """
        Set callback for incoming messages.

        Args:
            callback: Function to call when messages are received
        """
        self._message_callback = callback

    @abstractmethod
    async def connect(self) -> bool:
        """
        Establish connection to the traffic controller.

        Returns:
            True if connection successful
        """
        pass

    @abstractmethod
    async def disconnect(self):
        """Disconnect from the traffic controller."""
        pass

    @abstractmethod
    async def send_command(self, message: TrafficMessage) -> bool:
        """
        Send a command message to the controller.

        Args:
            message: Command message to send

        Returns:
            True if command sent successfully
        """
        pass

    @abstractmethod
    async def request_status(self) -> Optional[TrafficMessage]:
        """
        Request current status from the controller.

        Returns:
            Status message or None if request failed
        """
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """
        Check if adapter is connected to controller.

        Returns:
            True if connected
        """
        pass

    async def start(self):
        """
        Start the adapter (connect and begin operations).

        This is the main entry point for starting an adapter.
        """
        if not self.enabled:
            self.logger.info(f"Adapter {self.name} is disabled")
            return

        self.logger.info(f"Starting adapter {self.name}")

        try:
            # Establish connection
            connected = await self.connect()
            if not connected:
                raise ConnectionError(f"Failed to connect adapter {self.name}")

            # Start background tasks
            await self._start_background_tasks()

            self.logger.info(f"Adapter {self.name} started successfully")

        except Exception as e:
            self.logger.error(f"Failed to start adapter {self.name}: {e}")
            await self.stop()
            raise

    async def stop(self):
        """
        Stop the adapter (disconnect and cleanup).

        This should be called to gracefully shut down the adapter.
        """
        self.logger.info(f"Stopping adapter {self.name}")

        # Stop background tasks
        await self._stop_background_tasks()

        # Disconnect
        await self.disconnect()

        self.logger.info(f"Adapter {self.name} stopped")

    async def _start_background_tasks(self):
        """Start background tasks (polling, monitoring, etc.)."""
        # Default implementation - override in subclasses
        pass

    async def _stop_background_tasks(self):
        """Stop background tasks."""
        for task in self._tasks:
            if not task.done():
                task.cancel()

        if self._tasks:
            try:
                await asyncio.gather(*self._tasks, return_exceptions=True)
            except asyncio.CancelledError:
                pass

        self._tasks.clear()

    def _notify_message(self, message: TrafficMessage):
        """Notify listeners of incoming message."""
        if self._message_callback:
            try:
                self._message_callback(message)
            except Exception as e:
                self.logger.error(f"Error in message callback: {e}")

    def _create_error_message(self, error_code: str, error_message: str) -> TrafficMessage:
        """Create an error message."""
        return TrafficMessage.create_error(
            controller_id=self.controller_id,
            error_code=error_code,
            error_message=error_message
        )

    def _validate_message_for_adapter(self, message: TrafficMessage) -> bool:
        """
        Validate that a message is appropriate for this adapter.

        Args:
            message: Message to validate

        Returns:
            True if message is valid for this adapter
        """
        # Check if message is for this controller
        if message.controller_id and message.controller_id != self.controller_id:
            return False

        return True

    async def health_check(self) -> Dict[str, Any]:
        """
        Perform health check on the adapter.

        Returns:
            Health status dictionary
        """
        return {
            'adapter': self.name,
            'connected': self.is_connected(),
            'enabled': self.enabled,
            'controller_id': self.controller_id,
            'last_check': asyncio.get_event_loop().time()
        }

    def get_stats(self) -> Dict[str, Any]:
        """
        Get adapter statistics.

        Returns:
            Statistics dictionary
        """
        return {
            'adapter': self.name,
            'messages_sent': getattr(self, '_messages_sent', 0),
            'messages_received': getattr(self, '_messages_received', 0),
            'errors': getattr(self, '_error_count', 0),
            'uptime': getattr(self, '_start_time', None)
        }

    def __str__(self) -> str:
        """String representation."""
        return f"{self.__class__.__name__}(name={self.name}, controller={self.controller_id}, connected={self.is_connected()})"


class PollingAdapter(BaseAdapter):
    """
    Base class for adapters that poll for status updates.
    """

    def __init__(self, name: str, config: AdapterModel):
        super().__init__(name, config)
        self.polling_interval = config.polling_interval
        self._polling_task: Optional[asyncio.Task] = None

    async def _start_background_tasks(self):
        """Start polling task."""
        if self.polling_interval > 0:
            self._polling_task = asyncio.create_task(self._polling_loop())
            self._tasks.append(self._polling_task)

    async def _polling_loop(self):
        """Main polling loop."""
        while True:
            try:
                if self.is_connected():
                    status_message = await self.request_status()
                    if status_message:
                        self._notify_message(status_message)

                await asyncio.sleep(self.polling_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in polling loop: {e}")
                await asyncio.sleep(1)  # Brief pause before retry


class EventDrivenAdapter(BaseAdapter):
    """
    Base class for adapters that receive events asynchronously.
    """

    def __init__(self, name: str, config: AdapterModel):
        super().__init__(name, config)
        self._event_task: Optional[asyncio.Task] = None

    async def _start_background_tasks(self):
        """Start event listening task."""
        self._event_task = asyncio.create_task(self._event_loop())
        self._tasks.append(self._event_task)

    @abstractmethod
    async def _event_loop(self):
        """Main event listening loop."""
        pass