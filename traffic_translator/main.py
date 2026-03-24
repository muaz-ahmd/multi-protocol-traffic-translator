"""
Traffic Translator Main Application

Orchestrates multi-protocol traffic signal control with MQTT as the central hub.
"""

import asyncio
import logging
import signal
import sys
import time
from typing import Any, Dict, List, Optional, Set
import yaml

from .core.message import TrafficMessage
from .core.translation_engine import TranslationEngine, ValidationError, ConflictError
from .core.state_aggregator import StateAggregator
from .core.decision_engine_interface import DecisionEngineManager
from .core.feedback_listener import FeedbackListener

from .adapters.mqtt_adapter import MQTTAdapter
from .adapters.ntcip_adapter import NTCIPAdapter
from .adapters.plc_adapter import ModbusAdapter
from .adapters.relay_adapter import GPIOAdapter
from .adapters.rest_adapter import RESTAdapter
from .config.models import AppConfig, AdapterModel
from .core.logger import setup_logger


class AdapterRegistry:
    """Registry for dynamically creating protocol adapters."""
    _adapters = {}

    @classmethod
    def register(cls, adapter_type: str, adapter_class: type):
        cls._adapters[adapter_type] = adapter_class

    @classmethod
    def create(cls, name: str, config: AdapterModel):
        adapter_class = cls._adapters.get(config.type)
        if adapter_class:
            return adapter_class(name, config)
        return None

# Register default adapters
AdapterRegistry.register('mqtt', MQTTAdapter)
AdapterRegistry.register('ntcip', NTCIPAdapter)
AdapterRegistry.register('modbus', ModbusAdapter)
AdapterRegistry.register('gpio', GPIOAdapter)
AdapterRegistry.register('rest', RESTAdapter)


class TrafficTranslator:
    """
    Main traffic translator application.

    Coordinates multiple protocol adapters with MQTT as the central communication hub.
    """

    def __init__(self, config_path: str):
        """
        Initialize traffic translator.

        Args:
            config_path: Path to YAML configuration file
        """
        # Load configuration
        with open(config_path, 'r') as f:
            raw_config = yaml.safe_load(f)
            self.config = AppConfig(**raw_config)

        self.logger = setup_logger(__name__, level=self.config.logging.level, log_file=self.config.logging.file)

        # Core components
        self.translation_engine = TranslationEngine(self.config.translation)
        self.decision_engine = DecisionEngineManager(self.config.decision_engine)
        # State and Feedback
        self.state_aggregator = StateAggregator()
        self.feedback_listener = FeedbackListener(self.config.feedback)
        
        # Command Tracking (ACK System)
        self._pending_commands: Dict[str, TrafficMessage] = {}
        self._command_timeouts: Dict[str, float] = {}

        # Background tasks
        self._bg_tasks: Set[asyncio.Task] = set()
        self._running = False
        
        # Protocol adapters
        self.adapters: Dict[str, Any] = {}
        self.mqtt_adapter = None

        # Control flags
        self.shutdown_event = asyncio.Event()

        # Statistics
        self.stats = {
            'messages_received': 0,
            'commands_sent': 0,
            'errors_occurred': 0,
            'start_time': 0.0
        }

    def _setup_structured_logging(self):
        """Configure structured JSON logging."""
        # Simple implementation for now, could use python-json-logger
        root_logger = logging.getLogger()
        for handler in root_logger.handlers:
            root_logger.removeHandler(handler)
            
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            '{"timestamp": "%(asctime)s", "name": "%(name)s", "level": "%(levelname)s", "message": "%(message)s"}'
        )
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)

    async def _cleanup_loop(self):
        """Background loop for memory cleanup."""
        while self._running:
            try:
                await asyncio.sleep(60)
                self.translation_engine.cleanup_expired_states()
                self.state_aggregator.clear_stale_data()
            except Exception as e:
                self.logger.error(f"Error in cleanup loop: {e}")

    async def _command_timeout_loop(self):
        """Background loop to check for command timeouts."""
        while self._running:
            try:
                await asyncio.sleep(1)
                current_time = time.time()
                timed_out = [
                    cid for cid, expiry in self._command_timeouts.items()
                    if current_time > expiry
                ]
                
                for cid in timed_out:
                    cmd = self._pending_commands.get(cid)
                    if cmd:
                        self.logger.warning(f"Command {cid} TIMED OUT")
                        cmd.status = "TIMEOUT"
                        # Potentially trigger fallback or retry
                        
                    self._pending_commands.pop(cid, None)
                    self._command_timeouts.pop(cid, None)
                        
            except Exception as e:
                self.logger.error(f"Error in timeout loop: {e}")

    async def initialize(self):
        """Initialize all components."""
        self.logger.info("Initializing Traffic Translator...")

        try:
            # Initialize adapters
            await self._initialize_adapters()

            # Set message callbacks for adapters
            for adapter in self.adapters.values():
                adapter.set_message_callback(self._on_adapter_message)

            self.logger.info("Traffic Translator initialized successfully")

        except Exception as e:
            self.logger.error(f"Failed to initialize: {e}")
            raise

    async def start(self):
        """Start the traffic translator."""
        self.logger.info("Starting Traffic Translator...")
        self._setup_structured_logging()
        self._running = True
        self.stats['start_time'] = asyncio.get_event_loop().time()
        
        # Start background tasks
        self._bg_tasks.add(asyncio.create_task(self._cleanup_loop()))
        self._bg_tasks.add(asyncio.create_task(self._command_timeout_loop()))

        try:
            # Start feedback listener
            self.feedback_listener.set_message_callback(self._on_feedback_message)
            await self.feedback_listener.start_all()

            # Start adapters
            start_tasks = []
            for adapter in self.adapters.values():
                start_tasks.append(adapter.start())

            if start_tasks:
                await asyncio.gather(*start_tasks, return_exceptions=True)

            # Background loops are already started in start()
            pass

            self.logger.info("Traffic Translator started")

            # Main processing loop
            await self._main_loop()

        except Exception as e:
            self.logger.error(f"Error in main loop: {e}")
            self.stats['errors_occurred'] += 1
        finally:
            await self.stop()

    async def stop(self):
        """Stop the traffic translator."""
        self.logger.info("Stopping Traffic Translator...")
        self._running = False

        try:
            # Stop feedback listener
            await self.feedback_listener.stop_all()

            # Stop adapters
            stop_tasks = []
            for adapter in self.adapters.values():
                stop_tasks.append(adapter.stop())

            if stop_tasks:
                await asyncio.gather(*stop_tasks, return_exceptions=True)

            self.logger.info("Traffic Translator stopped")

        except Exception as e:
            self.logger.error(f"Error during shutdown: {e}")

    async def _initialize_adapters(self):
        """Initialize protocol adapters from configuration."""
        adapter_configs = self.config.adapters

        for adapter_name, adapter_config in adapter_configs.items():
            try:
                # Create adapter instance
                adapter = self._create_adapter(adapter_name, adapter_config)

                if adapter:
                    self.adapters[adapter_name] = adapter

                    # Keep reference to MQTT adapter
                    if adapter_config.type == 'mqtt':
                        self.mqtt_adapter = adapter

                    self.logger.info(f"Initialized adapter: {adapter_name} ({adapter_config.type})")

            except Exception as e:
                self.logger.error(f"Failed to initialize adapter {adapter_name}: {e}")

    def _create_adapter(self, name: str, config: AdapterModel):
        """Create adapter instance based on type using registry."""
        adapter = AdapterRegistry.create(name, config)
        
        if not adapter:
            self.logger.error(f"Unknown adapter type: {config.type}")
            
        return adapter

    def _on_adapter_message(self, message: TrafficMessage):
        """Handle incoming message from any adapter."""
        try:
            asyncio.create_task(self._message_callback(message))
        except Exception as e:
            self.logger.error(f"Error handling adapter message: {e}")

    def _on_feedback_message(self, message: TrafficMessage):
        """Handle feedback message from feedback listener."""
        try:
            asyncio.create_task(self._message_callback(message))
        except Exception as e:
            self.logger.error(f"Error handling feedback message: {e}")

    async def _message_callback(self, message: TrafficMessage):
        """
        Callback for messages from adapters (central hub).
        
        Args:
            message: The message received from an adapter
        """
        self.logger.debug(f"Received message from adapter: {message}")
        
        # Update State Aggregator
        self.state_aggregator.update(message)
        
        # Handle Command Lifecycle (ACK/Status/Feedback matching)
        if message.correlation_id and message.correlation_id in self._pending_commands:
            self._handle_command_feedback(message)
            
        # Continue standard processing...
        if message.message_type == 'command':
            await self._handle_command(message)
        elif message.message_type == 'status':
            self.translation_engine.update_phase_state(message)
        elif message.message_type == 'error':
            self.logger.error(f"Error from controller {message.controller_id}: {message.error_message}")

    def _handle_command_feedback(self, fb_msg: TrafficMessage):
        """Handle feedback/status linked to a pending command (ACK system)."""
        cmd_id = fb_msg.correlation_id
        cmd_msg = self._pending_commands.get(cmd_id)
        
        if not cmd_msg:
            return

        if fb_msg.message_type == 'status':
            # Check if the status confirms the command was executed
            if fb_msg.current_phase == cmd_msg.phase_id:
                self.logger.info(f"Command {cmd_id} ACKed and confirmed by controller state")
                cmd_msg.status = "EXECUTING"
                # Keep in pending until COMPLETED or replaced
            
        elif fb_msg.message_type == 'feedback':
            # Detector feedback might also indicate execution (e.g. vehicle flow)
            self.logger.debug(f"Received feedback for command {cmd_id}")
            
        elif fb_msg.message_type == 'error':
            self.logger.error(f"Command {cmd_id} FAILED: {fb_msg.error_message}")
            cmd_msg.status = "FAILED"
            self._pending_commands.pop(cmd_id, None)
            self._command_timeouts.pop(cmd_id, None)

    async def _handle_command(self, message: TrafficMessage):
        """Process incoming message through the translation engine."""
        try:
            self.logger.debug(f"Processing message: {message}")
            self.stats['messages_received'] += 1

            # Validate and optimize message
            processed_message = self.translation_engine.process_message(message)

            # Route message to appropriate adapters
            await self._route_message(processed_message)

        except Exception as e:
            self.logger.error(f"Error processing message: {e}")
            self.stats['errors_occurred'] += 1

    async def _route_message(self, processed_msg: TrafficMessage):
        """Route processed message to appropriate adapters."""
        # Always send to MQTT for central logging/distribution
        if self.mqtt_adapter and self.mqtt_adapter.is_connected():
            await self.mqtt_adapter.send_command(processed_msg)

        # Route to specific protocol adapters based on controller_id
        target_adapters = [
            adapter for name, adapter in self.adapters.items()
            if name != 'mqtt' and adapter.config.enabled and adapter.controller_id == processed_msg.controller_id
        ]

        # Concurrent dispatch to all target adapters
        results = await asyncio.gather(
            *[adapter.send_command(processed_msg) for adapter in target_adapters if adapter.is_connected()],
            return_exceptions=True
        )

        for adapter, success in zip(target_adapters, results):
            if isinstance(success, Exception):
                self.logger.error(f"Error sending command via {adapter.name}: {success}")
            elif not success:
                self.logger.error(f"Failed to send command via {adapter.name}")
            elif success and processed_msg.message_type == 'command':
                self.stats['commands_sent'] += 1

    def _get_target_adapters(self, controller_id: str) -> List[Any]:
        """Get adapters that should receive messages for a controller."""
        target_adapters = []

        for adapter in self.adapters.values():
            # Skip MQTT adapter (already handled)
            if adapter == self.mqtt_adapter:
                continue

            # Check if adapter handles this controller
            if adapter.controller_id == controller_id:
                target_adapters.append(adapter)

        return target_adapters

    async def _main_loop(self):
        """Main processing loop."""
        while self._running:
            try:
                # Periodic health checks
                await self._health_check()

                # Periodic statistics logging
                await self._log_statistics()

                # Wait for shutdown or timeout
                try:
                    await asyncio.wait_for(self.shutdown_event.wait(), timeout=60.0)
                except asyncio.TimeoutError:
                    pass  # Continue with next iteration

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in main loop: {e}")
                await asyncio.sleep(1)

    async def _health_check(self):
        """Perform health checks on all components."""
        # Check adapters
        for name, adapter in self.adapters.items():
            try:
                health = await adapter.health_check()
                if not health.get('connected', False):
                    self.logger.warning(f"Adapter {name} is not connected")
            except Exception as e:
                self.logger.error(f"Health check failed for adapter {name}: {e}")

        # Check feedback sources
        try:
            feedback_health = await self.feedback_listener.health_check()
            for name, healthy in feedback_health.items():
                if not healthy:
                    self.logger.warning(f"Feedback source {name} is not healthy")
        except Exception as e:
            self.logger.error(f"Feedback health check failed: {e}")

    async def _log_statistics(self):
        """Log current statistics."""
        uptime = asyncio.get_event_loop().time() - self.stats['start_time']
        self.logger.info(
            f"Stats: messages={self.stats['messages_received']}, "
            f"commands={self.stats['commands_sent']}, "
            f"errors={self.stats['errors_occurred']}, "
            f"uptime={uptime:.1f}s"
        )

    def get_status(self) -> Dict[str, Any]:
        """Get current system status."""
        return {
            'running': self._running,
            'adapters': {
                name: {
                    'connected': adapter.is_connected(),
                    'type': adapter.config.type,
                    'controller_id': adapter.controller_id
                }
                for name, adapter in self.adapters.items()
            },
            'feedback_sources': list(self.feedback_listener.get_active_sources()),
            'stats': self.stats.copy()
        }


async def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        prog='traffic-translator',
        description='Multi-protocol traffic signal controller translator'
    )
    parser.add_argument('-c', '--config', required=True,
                       help='Configuration YAML file')
    parser.add_argument('-v', '--verbose', action='count', default=0,
                       help='Increase verbosity (up to 3)')

    args = parser.parse_args()

    # Setup logging
    log_level = logging.WARNING
    if args.verbose == 1:
        log_level = logging.INFO
    elif args.verbose >= 2:
        log_level = logging.DEBUG

    logging.basicConfig(
        level=log_level,
        format='%(asctime)s %(name)s %(levelname)s: %(message)s'
    )

    # Create and run translator
    translator = TrafficTranslator(args.config)

    # Setup signal handlers
    def signal_handler(signum, frame):
        logging.info(f"Received signal {signum}, shutting down...")
        translator.shutdown_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        await translator.initialize()
        await translator.start()
    except KeyboardInterrupt:
        logging.info("Interrupted by user")
    except Exception as e:
        logging.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())