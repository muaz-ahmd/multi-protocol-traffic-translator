"""
NTCIP/SNMP Adapter for Traffic Controllers

Implements NTCIP 1202 protocol using SNMP for communication with traffic signal controllers.
"""

import logging
import asyncio
from typing import Dict, Any, Optional, List

try:
    from pysnmp.hlapi import *
    from pysnmp.entity.rfc3413.oneliner import cmdgen
    PYSNMP_AVAILABLE = True
except ImportError:
    PYSNMP_AVAILABLE = False

from .base_adapter import BaseAdapter, AdapterConfig, PollingAdapter
from ..core.message import TrafficMessage
from ..core.stmp_ntcip import NTCIP1202, NTCIPMessageMapper, SNMPTrapDefinitions


class NTCIPAdapter(PollingAdapter):
    """
    NTCIP/SNMP adapter for traffic signal controllers.

    Uses SNMP GET/SET operations to communicate with NTCIP 1202 compliant controllers.
    """

    def __init__(self, config: AdapterConfig):
        super().__init__(config)

        # SNMP configuration
        conn_params = config.connection_params or {}
        self.host = conn_params.get('host', 'localhost')
        self.port = conn_params.get('port', 161)
        self.community = conn_params.get('community', 'public')
        self.timeout = conn_params.get('timeout', 5)
        self.retries = conn_params.get('retries', 3)

        # NTCIP mapping
        self.phase_count = conn_params.get('phase_count', 8)
        self.detector_count = conn_params.get('detector_count', 16)

        # SNMP engine
        self.snmp_engine = SnmpEngine()

        # Statistics
        self._messages_sent = 0
        self._messages_received = 0
        self._error_count = 0

    async def connect(self) -> bool:
        """
        Establish SNMP connection to controller.

        Returns:
            True if connection successful
        """
        if not PYSNMP_AVAILABLE:
            self.logger.error("PySNMP not available. Install with: pip install pysnmp")
            return False

        try:
            self.logger.info(f"Connecting to NTCIP controller at {self.host}:{self.port}")

            # Test connection with a simple GET request
            error_indication, error_status, error_index, var_binds = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: getCmd(
                    SnmpEngine(),
                    CommunityData(self.community, mpModel=0),
                    UdpTransportTarget((self.host, self.port), timeout=self.timeout, retries=self.retries),
                    ContextData(),
                    ObjectType(ObjectIdentity('1.3.6.1.2.1.1.1.0'))  # sysDescr
                )
            )

            if error_indication:
                self.logger.error(f"SNMP connection failed: {error_indication}")
                return False

            if error_status:
                self.logger.error(f"SNMP error: {error_status.prettyPrint()}")
                return False

            self._connected = True
            self.logger.info(f"Successfully connected to NTCIP controller {self.controller_id}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to connect to NTCIP controller: {e}")
            return False

    async def disconnect(self):
        """Disconnect from controller."""
        self._connected = False
        self.logger.info(f"Disconnected from NTCIP controller {self.controller_id}")

    async def send_command(self, message: TrafficMessage) -> bool:
        """
        Send command to controller via SNMP SET.

        Args:
            message: Command message to send

        Returns:
            True if command sent successfully
        """
        if not self._validate_message_for_adapter(message):
            return False

        try:
            # Convert message to NTCIP commands
            ntcip_commands = NTCIPMessageMapper.message_to_ntcip_commands(message)

            if not ntcip_commands:
                self.logger.warning(f"No NTCIP commands generated for message: {message}")
                return False

            # Execute SNMP SET operations
            success = await self._execute_snmp_sets(ntcip_commands)

            if success:
                self._messages_sent += 1
                self.logger.debug(f"Sent NTCIP command: {message}")
            else:
                self._error_count += 1

            return success

        except Exception as e:
            self.logger.error(f"Failed to send NTCIP command: {e}")
            self._error_count += 1
            return False

    async def request_status(self) -> Optional[TrafficMessage]:
        """
        Request current status from controller.

        Returns:
            Status message or None if failed
        """
        try:
            # Get phase statuses
            phase_statuses = await self._get_phase_statuses()
            if not phase_statuses:
                return None

            # Get detector data
            detector_data = await self._get_detector_data()

            # Create status message
            message = TrafficMessage.create_status(
                controller_id=self.controller_id,
                current_phase=list(phase_statuses.keys())[0] if phase_statuses else 'unknown',
                phase_status=phase_statuses
            )

            if detector_data:
                message.detector_status = detector_data

            self._messages_received += 1
            return message

        except Exception as e:
            self.logger.error(f"Failed to request NTCIP status: {e}")
            self._error_count += 1
            return None

    def is_connected(self) -> bool:
        """Check SNMP connection status."""
        return self._connected

    async def _execute_snmp_sets(self, commands: List[Dict[str, Any]]) -> bool:
        """Execute multiple SNMP SET operations."""
        try:
            # Prepare SET request
            var_binds = []
            for cmd in commands:
                oid = ObjectIdentity(cmd['oid'])
                value = self._convert_value_for_snmp(cmd['value'])
                var_binds.append(ObjectType(oid, value))

            # Execute SET
            error_indication, error_status, error_index, var_binds_result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: setCmd(
                    self.snmp_engine,
                    CommunityData(self.community, mpModel=0),
                    UdpTransportTarget((self.host, self.port), timeout=self.timeout, retries=self.retries),
                    ContextData(),
                    *var_binds
                )
            )

            if error_indication:
                self.logger.error(f"SNMP SET failed: {error_indication}")
                return False

            if error_status:
                self.logger.error(f"SNMP SET error: {error_status.prettyPrint()}")
                return False

            return True

        except Exception as e:
            self.logger.error(f"SNMP SET execution failed: {e}")
            return False

    async def _get_phase_statuses(self) -> Dict[str, str]:
        """Get status of all phases."""
        statuses = {}

        try:
            # Prepare GET request for all phases
            var_binds = []
            for phase_num in range(1, self.phase_count + 1):
                oid = NTCIP1202.get_phase_status(phase_num)
                var_binds.append(ObjectType(ObjectIdentity(oid)))

            # Execute GET
            error_indication, error_status, error_index, var_binds_result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: getCmd(
                    self.snmp_engine,
                    CommunityData(self.community, mpModel=0),
                    UdpTransportTarget((self.host, self.port), timeout=self.timeout, retries=self.retries),
                    ContextData(),
                    *var_binds
                )
            )

            if error_indication:
                self.logger.error(f"SNMP GET phases failed: {error_indication}")
                return statuses

            if error_status:
                self.logger.error(f"SNMP GET phases error: {error_status.prettyPrint()}")
                return statuses

            # Parse results
            for i, var_bind in enumerate(var_binds_result):
                phase_num = i + 1
                value = int(var_bind[1])
                status = NTCIP1202.decode_phase_status(value)
                statuses[f'phase_{phase_num}'] = status

        except Exception as e:
            self.logger.error(f"Failed to get phase statuses: {e}")

        return statuses

    async def _get_detector_data(self) -> Dict[str, Any]:
        """Get detector data."""
        detector_data = {}

        try:
            # Prepare GET request for detector counts
            var_binds = []
            for detector_num in range(1, min(self.detector_count, 16) + 1):  # Limit to 16 for performance
                oid = NTCIP1202.get_detector_count(detector_num)
                var_binds.append(ObjectType(ObjectIdentity(oid)))

            # Execute GET
            error_indication, error_status, error_index, var_binds_result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: getCmd(
                    self.snmp_engine,
                    CommunityData(self.community, mpModel=0),
                    UdpTransportTarget((self.host, self.port), timeout=self.timeout, retries=self.retries),
                    ContextData(),
                    *var_binds
                )
            )

            if error_indication or error_status:
                # Don't log as error since detectors might not be configured
                return detector_data

            # Parse results
            for i, var_bind in enumerate(var_binds_result):
                detector_num = i + 1
                count = int(var_bind[1])
                detector_data[f'detector_{detector_num}'] = count

        except Exception as e:
            self.logger.debug(f"Failed to get detector data: {e}")

        return detector_data

    def _convert_value_for_snmp(self, value: Any) -> Any:
        """Convert Python value to SNMP-compatible value."""
        if isinstance(value, int):
            return Integer(value)
        elif isinstance(value, str):
            return OctetString(value.encode())
        else:
            return OctetString(str(value).encode())

    async def receive_trap(self, trap_data: Dict[str, Any]):
        """
        Handle incoming SNMP trap.

        Args:
            trap_data: Parsed trap data
        """
        try:
            # Convert trap to TrafficMessage
            message = self._trap_to_message(trap_data)
            if message:
                self._notify_message(message)
                self._messages_received += 1

        except Exception as e:
            self.logger.error(f"Failed to process SNMP trap: {e}")
            self._error_count += 1

    def _trap_to_message(self, trap_data: Dict[str, Any]) -> Optional[TrafficMessage]:
        """Convert SNMP trap to TrafficMessage."""
        trap_type = trap_data.get('trap_type')

        if trap_type == 'phaseChange':
            return TrafficMessage.create_status(
                controller_id=self.controller_id,
                current_phase=list(trap_data.get('phase_data', {}).keys())[0],
                phase_status=trap_data.get('phase_data', {})
            )

        elif trap_type == 'detectorActivation':
            return TrafficMessage.create_feedback(
                controller_id=self.controller_id,
                phase_id='detector',
                detector_status=trap_data.get('detector_data', {})
            )

        elif trap_type == 'faultCondition':
            return TrafficMessage.create_error(
                controller_id=self.controller_id,
                error_code='controller_fault',
                error_message=str(trap_data.get('fault_data', {}))
            )

        return None