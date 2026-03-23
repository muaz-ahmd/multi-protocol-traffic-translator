"""
NTCIP/SNMP Definitions for Traffic Translator

Implements NTCIP 1202 standard objects and SNMP trap handling for traffic controllers.
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass


# NTCIP 1202 OID Definitions
NTCIP_OIDS = {
    # Phase Control
    'phaseControl': '1.3.6.1.4.1.1206.4.2.1.1',
    'phaseStatus': '1.3.6.1.4.1.1206.4.2.1.1.1',
    'phaseGreen': '1.3.6.1.4.1.1206.4.2.1.1.2',
    'phaseYellow': '1.3.6.1.4.1.1206.4.2.1.1.3',
    'phaseRed': '1.3.6.1.4.1.1206.4.2.1.1.4',
    'phaseWalk': '1.3.6.1.4.1.1206.4.2.1.1.5',
    'phaseDontWalk': '1.3.6.1.4.1.1206.4.2.1.1.6',

    # Detector Data
    'detectorData': '1.3.6.1.4.1.1206.4.2.1.2',
    'detectorPresence': '1.3.6.1.4.1.1206.4.2.1.2.1',
    'detectorCount': '1.3.6.1.4.1.1206.4.2.1.2.2',
    'detectorOccupancy': '1.3.6.1.4.1.1206.4.2.1.2.3',
    'detectorSpeed': '1.3.6.1.4.1.1206.4.2.1.2.4',

    # Timing Parameters
    'timingParameters': '1.3.6.1.4.1.1206.4.2.1.3',
    'minimumGreen': '1.3.6.1.4.1.1206.4.2.1.3.1',
    'maximumGreen': '1.3.6.1.4.1.1206.4.2.1.3.2',
    'yellowChange': '1.3.6.1.4.1.1206.4.2.1.3.3',
    'redClear': '1.3.6.1.4.1.1206.4.2.1.3.4',
    'walkTime': '1.3.6.1.4.1.1206.4.2.1.3.5',
    'dontWalkTime': '1.3.6.1.4.1.1206.4.2.1.3.6',

    # Fault Monitoring
    'faultMonitoring': '1.3.6.1.4.1.1206.4.2.1.4',
    'controllerFault': '1.3.6.1.4.1.1206.4.2.1.4.1',
    'communicationFault': '1.3.6.1.4.1.1206.4.2.1.4.2',
    'powerFault': '1.3.6.1.4.1.1206.4.2.1.4.3',
    'detectorFault': '1.3.6.1.4.1.1206.4.2.1.4.4',

    # Preemption
    'preemption': '1.3.6.1.4.1.1206.4.2.1.5',
    'preemptState': '1.3.6.1.4.1.1206.4.2.1.5.1',
    'preemptType': '1.3.6.1.4.1.1206.4.2.1.5.2',
    'preemptPriority': '1.3.6.1.4.1.1206.4.2.1.5.3',
}


@dataclass
class NTCIPObject:
    """NTCIP MIB object definition."""
    oid: str
    name: str
    syntax: str
    access: str
    description: str
    value: Any = None


class NTCIP1202:
    """
    NTCIP 1202 Traffic Signal Controller Objects.

    Provides mapping between NTCIP objects and traffic translator messages.
    """

    # Phase status values (NTCIP 1202)
    PHASE_STATUS = {
        0: 'unknown',
        1: 'red',
        2: 'yellow',
        3: 'green',
        4: 'flash_red',
        5: 'flash_yellow',
        6: 'flash_green',
        7: 'preempt',
        8: 'priority'
    }

    # Detector presence values
    DETECTOR_PRESENCE = {
        0: 'no_vehicle',
        1: 'vehicle_present'
    }

    # Fault codes
    FAULT_CODES = {
        0: 'no_fault',
        1: 'controller_fault',
        2: 'communication_fault',
        3: 'power_fault',
        4: 'detector_fault',
        5: 'lamp_fault',
        6: 'conflict_monitor_fault'
    }

    @staticmethod
    def get_phase_status(phase_number: int) -> str:
        """
        Get OID for phase status.

        Args:
            phase_number: Phase number (1-16)

        Returns:
            OID string
        """
        return f"{NTCIP_OIDS['phaseStatus']}.{phase_number}"

    @staticmethod
    def get_detector_count(detector_number: int) -> str:
        """
        Get OID for detector count.

        Args:
            detector_number: Detector number (1-255)

        Returns:
            OID string
        """
        return f"{NTCIP_OIDS['detectorCount']}.{detector_number}"

    @staticmethod
    def get_timing_parameter(phase_number: int, parameter: str) -> str:
        """
        Get OID for timing parameter.

        Args:
            phase_number: Phase number (1-16)
            parameter: Parameter name ('minimumGreen', 'maximumGreen', etc.)

        Returns:
            OID string
        """
        base_oid = NTCIP_OIDS.get(parameter)
        if not base_oid:
            raise ValueError(f"Unknown timing parameter: {parameter}")
        return f"{base_oid}.{phase_number}"

    @staticmethod
    def decode_phase_status(value: int) -> str:
        """
        Decode phase status value to human-readable string.

        Args:
            value: Raw NTCIP phase status value

        Returns:
            Human-readable phase status
        """
        return NTCIP1202.PHASE_STATUS.get(value, 'unknown')

    @staticmethod
    def decode_detector_presence(value: int) -> str:
        """
        Decode detector presence value.

        Args:
            value: Raw detector presence value

        Returns:
            Human-readable presence status
        """
        return NTCIP1202.DETECTOR_PRESENCE.get(value, 'unknown')

    @staticmethod
    def decode_fault_code(value: int) -> str:
        """
        Decode fault code.

        Args:
            value: Raw fault code value

        Returns:
            Human-readable fault description
        """
        return NTCIP1202.FAULT_CODES.get(value, 'unknown_fault')

    @staticmethod
    def encode_phase_command(command: str) -> int:
        """
        Encode phase command to NTCIP value.

        Args:
            command: Command string ('green', 'yellow', 'red', etc.)

        Returns:
            NTCIP phase status value
        """
        command_map = {
            'red': 1,
            'yellow': 2,
            'green': 3,
            'flash_red': 4,
            'flash_yellow': 5,
            'flash_green': 6,
            'preempt': 7,
            'priority': 8
        }

        return command_map.get(command.lower(), 0)  # 0 = unknown/off


class SNMPTrapDefinitions:
    """
    SNMP Trap definitions for traffic controller events.
    """

    # Standard SNMP trap OIDs
    TRAP_OIDS = {
        'coldStart': '1.3.6.1.6.3.1.1.5.1',
        'warmStart': '1.3.6.1.6.3.1.1.5.2',
        'linkDown': '1.3.6.1.6.3.1.1.5.3',
        'linkUp': '1.3.6.1.6.3.1.1.5.4',
        'authenticationFailure': '1.3.6.1.6.3.1.1.5.5',
    }

    # NTCIP-specific trap OIDs
    NTCIP_TRAPS = {
        'phaseChange': '1.3.6.1.4.1.1206.4.2.1.0.1',
        'detectorActivation': '1.3.6.1.4.1.1206.4.2.1.0.2',
        'faultCondition': '1.3.6.1.4.1.1206.4.2.1.0.3',
        'preemptionRequest': '1.3.6.1.4.1.1206.4.2.1.0.4',
        'timingChange': '1.3.6.1.4.1.1206.4.2.1.0.5',
    }

    @staticmethod
    def get_trap_info(trap_oid: str) -> Dict[str, Any]:
        """
        Get information about a trap OID.

        Args:
            trap_oid: Trap OID string

        Returns:
            Dictionary with trap information
        """
        all_traps = {**SNMPTrapDefinitions.TRAP_OIDS, **SNMPTrapDefinitions.NTCIP_TRAPS}

        for name, oid in all_traps.items():
            if trap_oid == oid:
                return {
                    'name': name,
                    'oid': oid,
                    'type': 'ntcip' if oid in SNMPTrapDefinitions.NTCIP_TRAPS.values() else 'standard'
                }

        return {
            'name': 'unknown',
            'oid': trap_oid,
            'type': 'unknown'
        }

    @staticmethod
    def parse_ntcip_trap(trap_oid: str, varbinds: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Parse NTCIP-specific trap variables.

        Args:
            trap_oid: Trap OID
            varbinds: Variable bindings from trap

        Returns:
            Parsed trap data
        """
        trap_info = SNMPTrapDefinitions.get_trap_info(trap_oid)

        if trap_info['type'] != 'ntcip':
            return {'trap_type': 'non_ntcip', 'data': varbinds}

        # Parse NTCIP trap data
        parsed_data = {
            'trap_type': trap_info['name'],
            'timestamp': None,
            'controller_id': None,
            'phase_data': {},
            'detector_data': {},
            'fault_data': {}
        }

        for varbind in varbinds:
            oid = varbind.get('oid', '')
            value = varbind.get('value')

            # Extract data based on OID patterns
            if oid.startswith(NTCIP_OIDS['phaseStatus']):
                phase_num = oid.split('.')[-1]
                parsed_data['phase_data'][f'phase_{phase_num}'] = NTCIP1202.decode_phase_status(value)

            elif oid.startswith(NTCIP_OIDS['detectorCount']):
                detector_num = oid.split('.')[-1]
                parsed_data['detector_data'][f'detector_{detector_num}'] = value

            elif oid.startswith(NTCIP_OIDS['controllerFault']):
                parsed_data['fault_data']['controller'] = NTCIP1202.decode_fault_code(value)

            # Add more parsing as needed...

        return parsed_data


class NTCIPMessageMapper:
    """
    Maps between TrafficMessages and NTCIP objects.
    """

    @staticmethod
    def message_to_ntcip_commands(message: 'TrafficMessage') -> List[Dict[str, Any]]:
        """
        Convert TrafficMessage to NTCIP commands.

        Args:
            message: TrafficMessage to convert

        Returns:
            List of NTCIP command dictionaries
        """
        commands = []

        if message.message_type != 'command':
            return commands

        phase_id = message.phase_id
        command = message.command

        if not phase_id or not command:
            return commands

        # Phase control command
        if command in ['green', 'yellow', 'red', 'flash']:
            oid = NTCIP1202.get_phase_status(int(phase_id))
            value = NTCIP1202.encode_phase_command(command)

            commands.append({
                'oid': oid,
                'value': value,
                'type': 'SET'
            })

        # Duration/timing commands
        if message.duration:
            if command == 'green':
                oid = NTCIP1202.get_timing_parameter(int(phase_id), 'maximumGreen')
                commands.append({
                    'oid': oid,
                    'value': message.duration,
                    'type': 'SET'
                })

        return commands

    @staticmethod
    def ntcip_status_to_message(controller_id: str, oid: str, value: Any) -> Optional['TrafficMessage']:
        """
        Convert NTCIP status update to TrafficMessage.

        Args:
            controller_id: Controller identifier
            oid: NTCIP OID
            value: OID value

        Returns:
            TrafficMessage or None if not mappable
        """
        from .message import TrafficMessage

        # Phase status update
        if oid.startswith(NTCIP_OIDS['phaseStatus']):
            phase_num = oid.split('.')[-1]
            phase_status = NTCIP1202.decode_phase_status(value)

            return TrafficMessage.create_status(
                controller_id=controller_id,
                current_phase=f"phase_{phase_num}",
                phase_status={
                    f"phase_{phase_num}": phase_status
                }
            )

        # Detector data
        elif oid.startswith(NTCIP_OIDS['detectorCount']):
            detector_num = oid.split('.')[-1]

            return TrafficMessage.create_feedback(
                controller_id=controller_id,
                phase_id=f"detector_{detector_num}",
                detector_status={
                    f"detector_{detector_num}": value
                }
            )

        # Fault status
        elif oid.startswith(NTCIP_OIDS['controllerFault']):
            fault_desc = NTCIP1202.decode_fault_code(value)

            return TrafficMessage.create_error(
                controller_id=controller_id,
                error_code='controller_fault',
                error_message=f"Controller fault: {fault_desc}"
            )

        return None