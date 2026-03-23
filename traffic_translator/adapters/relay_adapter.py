"""
GPIO Relay Adapter for Traffic Controllers

Implements GPIO control for relay-based traffic signal controllers using Raspberry Pi.
"""

import logging
import asyncio
from typing import Dict, Any, Optional, List

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False

from .base_adapter import BaseAdapter, PollingAdapter
from ..config.models import AdapterModel
from ..core.message import TrafficMessage


class GPIOAdapter(PollingAdapter):
    """
    GPIO adapter for relay-based traffic controllers.

    Controls traffic signals through GPIO pins connected to relays.
    Designed for Raspberry Pi and similar single-board computers.
    """

    def __init__(self, name: str, config: AdapterModel):
        super().__init__(name, config)

        # GPIO configuration
        conn_params = config.connection_params or {}
        self.gpio_mode = conn_params.get('gpio_mode', 'BCM')  # BCM or BOARD
        self.pin_mapping = conn_params.get('pin_mapping', {
            'phase_1_red': 17,
            'phase_1_yellow': 18,
            'phase_1_green': 27,
            'phase_2_red': 22,
            'phase_2_yellow': 23,
            'phase_2_green': 24,
            # Add more phases as needed
        })

        # Phase configuration
        self.phase_config = conn_params.get('phase_config', {
            'phase_1': {'red': 'phase_1_red', 'yellow': 'phase_1_yellow', 'green': 'phase_1_green'},
            'phase_2': {'red': 'phase_2_red', 'yellow': 'phase_2_yellow', 'green': 'phase_2_green'},
        })

        # GPIO state tracking
        self.pin_states = {}

        # Statistics
        self._messages_sent = 0
        self._messages_received = 0
        self._error_count = 0

    async def connect(self) -> bool:
        """
        Initialize GPIO interface.

        Returns:
            True if GPIO initialized successfully
        """
        if not GPIO_AVAILABLE:
            self.logger.error("RPi.GPIO not available. Install with: pip install RPi.GPIO")
            return False

        try:
            self.logger.info("Initializing GPIO interface")

            # Set GPIO mode
            if self.gpio_mode == 'BCM':
                GPIO.setmode(GPIO.BCM)
            else:
                GPIO.setmode(GPIO.BOARD)

            # Setup pins as outputs
            for pin_name, pin_number in self.pin_mapping.items():
                GPIO.setup(pin_number, GPIO.OUT)
                GPIO.output(pin_number, GPIO.LOW)  # Initialize to off
                self.pin_states[pin_name] = False

            # Cleanup function for shutdown
            import atexit
            atexit.register(GPIO.cleanup)

            self._connected = True
            self.logger.info(f"GPIO interface initialized with {len(self.pin_mapping)} pins")
            return True

        except Exception as e:
            self.logger.error(f"Failed to initialize GPIO: {e}")
            return False

    async def disconnect(self):
        """Cleanup GPIO interface."""
        if GPIO_AVAILABLE:
            try:
                GPIO.cleanup()
            except Exception as e:
                self.logger.error(f"Error during GPIO cleanup: {e}")

        self._connected = False
        self.logger.info("GPIO interface cleaned up")

    async def send_command(self, message: TrafficMessage) -> bool:
        """
        Send command by controlling GPIO pins.

        Args:
            message: Command message to send

        Returns:
            True if command executed successfully
        """
        if not self._validate_message_for_adapter(message):
            return False

        try:
            # Convert message to GPIO operations
            operations = self._message_to_gpio_operations(message)

            if not operations:
                self.logger.warning(f"No GPIO operations generated for message: {message}")
                return False

            # Execute operations
            success = await self._execute_gpio_operations(operations)

            if success:
                self._messages_sent += 1
                self.logger.debug(f"Executed GPIO command: {message}")
            else:
                self._error_count += 1

            return success

        except Exception as e:
            self.logger.error(f"Failed to execute GPIO command: {e}")
            self._error_count += 1
            return False

    async def request_status(self) -> Optional[TrafficMessage]:
        """
        Read current GPIO pin states.

        Returns:
            Status message with current pin states
        """
        try:
            # Read current pin states
            current_states = {}
            for pin_name, pin_number in self.pin_mapping.items():
                if GPIO_AVAILABLE:
                    state = GPIO.input(pin_number)
                    current_states[pin_name] = bool(state)
                else:
                    current_states[pin_name] = self.pin_states.get(pin_name, False)

            # Convert to phase statuses
            phase_statuses = self._gpio_states_to_phase_statuses(current_states)

            # Create status message
            message = TrafficMessage.create_status(
                controller_id=self.controller_id,
                current_phase=list(phase_statuses.keys())[0] if phase_statuses else 'unknown',
                phase_status=phase_statuses
            )

            message.protocol_data = {'gpio_states': current_states}

            self._messages_received += 1
            return message

        except Exception as e:
            self.logger.error(f"Failed to read GPIO status: {e}")
            self._error_count += 1
            return None

    def is_connected(self) -> bool:
        """Check GPIO interface status."""
        return self._connected

    def _message_to_gpio_operations(self, message: TrafficMessage) -> List[Dict[str, Any]]:
        """Convert TrafficMessage to GPIO operations."""
        operations = []

        if message.message_type != 'command':
            return operations

        phase_id = message.phase_id
        command = message.command

        if not phase_id or not command:
            return operations

        # Get phase pin configuration
        phase_pins = self.phase_config.get(phase_id, {})

        if command == 'red':
            # Turn on red, turn off others
            operations.extend(self._set_phase_lights(phase_pins, red=True, yellow=False, green=False))

        elif command == 'yellow':
            # Turn on yellow, turn off others
            operations.extend(self._set_phase_lights(phase_pins, red=False, yellow=True, green=False))

        elif command == 'green':
            # Turn on green, turn off others
            operations.extend(self._set_phase_lights(phase_pins, red=False, yellow=False, green=True))

        elif command == 'flash':
            # For flash, we could implement flashing logic
            # For now, just turn on red
            operations.extend(self._set_phase_lights(phase_pins, red=True, yellow=False, green=False))

        elif command == 'preempt':
            # Emergency preemption - flash all lights
            for phase_id_config, pins in self.phase_config.items():
                operations.extend(self._set_phase_lights(pins, red=True, yellow=True, green=True))

        return operations

    def _set_phase_lights(self, phase_pins: Dict[str, str], red: bool, yellow: bool, green: bool) -> List[Dict[str, Any]]:
        """Generate operations to set phase lights."""
        operations = []

        pin_commands = {
            'red': red,
            'yellow': yellow,
            'green': green
        }

        for light_type, state in pin_commands.items():
            pin_name = phase_pins.get(light_type)
            if pin_name and pin_name in self.pin_mapping:
                operations.append({
                    'pin_name': pin_name,
                    'pin_number': self.pin_mapping[pin_name],
                    'state': state
                })

        return operations

    async def _execute_gpio_operations(self, operations: List[Dict[str, Any]]) -> bool:
        """Execute GPIO pin operations."""
        try:
            for op in operations:
                pin_number = op['pin_number']
                state = op['state']
                pin_name = op['pin_name']

                if GPIO_AVAILABLE:
                    GPIO.output(pin_number, GPIO.HIGH if state else GPIO.LOW)

                # Update tracked state
                self.pin_states[pin_name] = state

                self.logger.debug(f"Set GPIO pin {pin_number} ({pin_name}) to {state}")

            return True

        except Exception as e:
            self.logger.error(f"GPIO operation failed: {e}")
            return False

    def _gpio_states_to_phase_statuses(self, gpio_states: Dict[str, bool]) -> Dict[str, str]:
        """Convert GPIO pin states to phase statuses."""
        phase_statuses = {}

        for phase_id, pins in self.phase_config.items():
            # Determine phase status based on active lights
            red_pin = pins.get('red')
            yellow_pin = pins.get('yellow')
            green_pin = pins.get('green')

            red_on = gpio_states.get(red_pin, False)
            yellow_on = gpio_states.get(yellow_pin, False)
            green_on = gpio_states.get(green_pin, False)

            if green_on:
                status = 'green'
            elif yellow_on:
                status = 'yellow'
            elif red_on:
                status = 'red'
            else:
                status = 'off'

            phase_statuses[phase_id] = status

        return phase_statuses

    async def flash_lights(self, phase_id: str, duration: float = 1.0, count: int = 5):
        """
        Flash lights for a phase (used for preemption or warnings).

        Args:
            phase_id: Phase to flash
            duration: Duration of each flash in seconds
            count: Number of flashes
        """
        if phase_id not in self.phase_config:
            return

        phase_pins = self.phase_config[phase_id]

        try:
            for _ in range(count):
                # Turn all lights on
                operations = self._set_phase_lights(phase_pins, red=True, yellow=True, green=True)
                await self._execute_gpio_operations(operations)

                await asyncio.sleep(duration / 2)

                # Turn all lights off
                operations = self._set_phase_lights(phase_pins, red=False, yellow=False, green=False)
                await self._execute_gpio_operations(operations)

                await asyncio.sleep(duration / 2)

        except Exception as e:
            self.logger.error(f"Error during light flashing: {e}")

    def get_pin_states(self) -> Dict[str, bool]:
        """Get current state of all GPIO pins."""
        return self.pin_states.copy()