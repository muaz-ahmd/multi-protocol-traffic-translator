"""
Modbus/PLC Adapter for Traffic Controllers

Implements Modbus TCP/RTU protocol for communication with PLC-based traffic controllers.
"""

import logging
import asyncio
from typing import Dict, Any, Optional, List

try:
    from pymodbus.client import AsyncModbusTcpClient, AsyncModbusSerialClient
    from pymodbus.exceptions import ModbusException
    PYMODBUS_AVAILABLE = True
except ImportError:
    PYMODBUS_AVAILABLE = False

from .base_adapter import BaseAdapter, PollingAdapter
from ..config.models import AdapterModel
from ..core.message import TrafficMessage


class ModbusAdapter(PollingAdapter):
    """
    Modbus adapter for PLC-based traffic controllers.

    Supports both Modbus TCP and RTU for communication with industrial controllers.
    """

    def __init__(self, name: str, config: AdapterModel):
        super().__init__(name, config)

        # Modbus configuration
        conn_params = config.connection_params or {}
        self.protocol = conn_params.get('protocol', 'tcp')  # 'tcp' or 'rtu'
        self.host = conn_params.get('host', 'localhost')
        self.port = conn_params.get('port', 502)
        self.unit_id = conn_params.get('unit_id', 1)

        # RTU specific
        self.serial_port = conn_params.get('serial_port', '/dev/ttyUSB0')
        self.baudrate = conn_params.get('baudrate', 9600)
        self.parity = conn_params.get('parity', 'N')
        self.stopbits = conn_params.get('stopbits', 1)

        # Register mapping
        self.register_map = conn_params.get('register_map', {
            'phase_control': {'address': 1000, 'count': 8, 'type': 'coil'},
            'phase_status': {'address': 1100, 'count': 8, 'type': 'holding'},
            'detector_data': {'address': 1200, 'count': 16, 'type': 'input'},
            'fault_status': {'address': 1300, 'count': 4, 'type': 'holding'},
        })

        # Modbus client
        self.client = None

        # Statistics
        self._messages_sent = 0
        self._messages_received = 0
        self._error_count = 0

    async def connect(self) -> bool:
        """
        Establish Modbus connection to PLC.

        Returns:
            True if connection successful
        """
        if not PYMODBUS_AVAILABLE:
            self.logger.error("PyModbus not available. Install with: pip install pymodbus")
            return False

        try:
            self.logger.info(f"Connecting to Modbus PLC at {self.host}:{self.port}")

            # Create appropriate async client
            if self.protocol.lower() == 'tcp':
                self.client = AsyncModbusTcpClient(
                    host=self.host,
                    port=self.port,
                    timeout=self.config.timeout
                )
            else:  # RTU
                self.client = AsyncModbusSerialClient(
                    port=self.serial_port,
                    baudrate=self.baudrate,
                    parity=self.parity,
                    stopbits=self.stopbits,
                    timeout=self.config.timeout
                )

            # Test connection (native async)
            connected = await self.client.connect()

            if not connected:
                self.logger.error("Failed to connect to Modbus device")
                return False

            # Test with a simple read
            try:
                result = await self.client.read_holding_registers(
                    0, 1, slave=self.unit_id
                )
                if result.isError():
                    self.logger.warning(f"Modbus test read failed: {result}")
                    # Don't fail connection for this
            except Exception as e:
                self.logger.debug(f"Modbus test read exception: {e}")

            self._connected = True
            self.logger.info(f"Successfully connected to Modbus PLC {self.controller_id}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to connect to Modbus PLC: {e}")
            return False

    async def disconnect(self):
        """Disconnect from PLC."""
        if self.client:
            self.client.close()
        self._connected = False
        self.logger.info(f"Disconnected from Modbus PLC {self.controller_id}")

    async def send_command(self, message: TrafficMessage) -> bool:
        """
        Send command to PLC via Modbus write.

        Args:
            message: Command message to send

        Returns:
            True if command sent successfully
        """
        if not self._validate_message_for_adapter(message):
            return False

        try:
            # Convert message to Modbus operations
            operations = self._message_to_modbus_operations(message)

            if not operations:
                self.logger.warning(f"No Modbus operations generated for message: {message}")
                return False

            # Execute operations
            success = await self._execute_modbus_operations(operations)

            if success:
                self._messages_sent += 1
                self.logger.debug(f"Sent Modbus command: {message}")
            else:
                self._error_count += 1

            return success

        except Exception as e:
            self.logger.error(f"Failed to send Modbus command: {e}")
            self._error_count += 1
            return False

    async def request_status(self) -> Optional[TrafficMessage]:
        """
        Request current status from PLC.

        Returns:
            Status message or None if failed
        """
        try:
            # Read phase statuses
            phase_statuses = await self._read_phase_statuses()
            if not phase_statuses:
                return None

            # Read detector data
            detector_data = await self._read_detector_data()

            # Read fault status
            fault_data = await self._read_fault_status()

            # Create status message
            message = TrafficMessage.create_status(
                controller_id=self.controller_id,
                current_phase=list(phase_statuses.keys())[0] if phase_statuses else 'unknown',
                phase_status=phase_statuses
            )

            if detector_data:
                message.detector_status = detector_data

            if fault_data:
                message.protocol_data = {'faults': fault_data}

            self._messages_received += 1
            return message

        except Exception as e:
            self.logger.error(f"Failed to request Modbus status: {e}")
            self._error_count += 1
            return None

    def is_connected(self) -> bool:
        """Check Modbus connection status."""
        return self._connected and self.client and self.client.is_socket_open()

    def _message_to_modbus_operations(self, message: TrafficMessage) -> List[Dict[str, Any]]:
        """Convert TrafficMessage to Modbus operations."""
        operations = []

        if message.message_type != 'command':
            return operations

        phase_id = message.phase_id
        command = message.command

        if not phase_id or not command:
            return operations

        # Map phase commands to register/coil operations
        phase_num = int(phase_id.replace('phase_', ''))

        if command in ['green', 'yellow', 'red', 'flash']:
            # Write to phase control register
            reg_info = self.register_map.get('phase_control', {})
            if reg_info.get('type') == 'coil':
                # Coil write for direct control
                address = reg_info['address'] + phase_num - 1
                value = self._command_to_coil_value(command)
                operations.append({
                    'type': 'write_coil',
                    'address': address,
                    'value': value
                })
            elif reg_info.get('type') == 'holding':
                # Holding register write
                address = reg_info['address'] + phase_num - 1
                value = self._command_to_register_value(command)
                operations.append({
                    'type': 'write_register',
                    'address': address,
                    'value': value
                })

        return operations

    def _command_to_coil_value(self, command: str) -> bool:
        """Convert command to coil boolean value."""
        # Simple mapping: green/yellow = True, red/flash = False
        return command in ['green', 'yellow']

    def _command_to_register_value(self, command: str) -> int:
        """Convert command to register integer value."""
        command_map = {
            'red': 1,
            'yellow': 2,
            'green': 3,
            'flash': 4
        }
        return command_map.get(command, 0)

    async def _execute_modbus_operations(self, operations: List[Dict[str, Any]]) -> bool:
        """Execute multiple Modbus operations."""
        try:
            for op in operations:
                op_type = op['type']

                if op_type == 'write_coil':
                    result = await self.client.write_coil(
                        op['address'], op['value'], slave=self.unit_id
                    )
                elif op_type == 'write_register':
                    result = await self.client.write_register(
                        op['address'], op['value'], slave=self.unit_id
                    )
                else:
                    self.logger.error(f"Unknown Modbus operation type: {op_type}")
                    return False

                if result.isError():
                    self.logger.error(f"Modbus {op_type} failed: {result}")
                    return False

            return True

        except Exception as e:
            self.logger.error(f"Modbus operation execution failed: {e}")
            return False

    async def _read_phase_statuses(self) -> Dict[str, str]:
        """Read phase status registers."""
        statuses = {}

        try:
            reg_info = self.register_map.get('phase_status', {})
            if not reg_info:
                return statuses

            address = reg_info['address']
            count = reg_info['count']

            result = await self.client.read_holding_registers(
                address, count, slave=self.unit_id
            )

            if result.isError():
                self.logger.debug(f"Failed to read phase statuses: {result}")
                return statuses

            # Convert register values to phase statuses
            for i, value in enumerate(result.registers):
                phase_num = i + 1
                status = self._register_value_to_status(value)
                statuses[f'phase_{phase_num}'] = status

        except Exception as e:
            self.logger.error(f"Error reading phase statuses: {e}")

        return statuses

    async def _read_detector_data(self) -> Dict[str, Any]:
        """Read detector data registers."""
        detector_data = {}

        try:
            reg_info = self.register_map.get('detector_data', {})
            if not reg_info:
                return detector_data

            address = reg_info['address']
            count = reg_info['count']

            if reg_info.get('type') == 'input':
                result = await self.client.read_input_registers(
                    address, count, slave=self.unit_id
                )
            else:
                result = await self.client.read_holding_registers(
                    address, count, slave=self.unit_id
                )

            if result.isError():
                self.logger.debug(f"Failed to read detector data: {result}")
                return detector_data

            # Convert to detector counts
            for i, value in enumerate(result.registers):
                detector_num = i + 1
                detector_data[f'detector_{detector_num}'] = value

        except Exception as e:
            self.logger.error(f"Error reading detector data: {e}")

        return detector_data

    async def _read_fault_status(self) -> Dict[str, Any]:
        """Read fault status registers."""
        fault_data = {}

        try:
            reg_info = self.register_map.get('fault_status', {})
            if not reg_info:
                return fault_data

            address = reg_info['address']
            count = reg_info['count']

            result = await self.client.read_holding_registers(
                address, count, slave=self.unit_id
            )

            if result.isError():
                self.logger.debug(f"Failed to read fault status: {result}")
                return fault_data

            fault_data = {
                'fault_registers': result.registers,
                'has_faults': any(result.registers)
            }

        except Exception as e:
            self.logger.error(f"Error reading fault status: {e}")

        return fault_data

    def _register_value_to_status(self, value: int) -> str:
        """Convert register value to phase status string."""
        status_map = {
            0: 'unknown',
            1: 'red',
            2: 'yellow',
            3: 'green',
            4: 'flash_red',
            5: 'flash_yellow',
            6: 'flash_green'
        }
        return status_map.get(value, 'unknown')