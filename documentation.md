# Multi-Protocol Traffic Translator - Detailed Documentation

## Overview

The Multi-Protocol Traffic Translator is a sophisticated, production-ready system designed to serve as a universal communication hub for traffic signal controllers. It enables seamless integration between different communication protocols, with MQTT serving as the central interchange language for all traffic control operations.

## Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Cloud Layer (MQTT Hub)                   │
│  ┌─────────────────────────────────────────────────────┐    │
│  │            Decision Engine (AI/Rules)              │    │
│  └─────────────────┬───────────────────────────────────┘    │
└─────────────────────┼───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│              State Aggregator (Global Cache)                │
│  (Central source of truth for all controllers & phases)     │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│         Translation Engine (Safety & Lifecycle)             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ Validation │ Conflict Detection │ Lifecycle Tracking │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────┬───────────────────────────────────────┘
                      │
    ┌─────────────────┼─────────────────┐
    │                 │                 │
┌───▼───┐  ┌──────────▼─────────┐  ┌───▼───┐
│NTCIP  │  │   GPIO Relay      │  │Modbus │
│Adapter│  │   (Controller)    │  │Adapter│
└───┬───┘  └──────────┬─────────┘  └───┬───┘
    │                 │                 │
    └─────────────────┼─────────────────┘
                      │
            ┌─────────▼─────────┐
            │ Feedback Listener │
            │ (SNMP/Modbus/In)  │
            └───────────────────┘
```

### Core Components

#### 1. Main Application (`traffic_translator/main.py`)

**Purpose**: Orchestrates the entire traffic translator system, managing adapters, translation engine, decision engines, and feedback listeners.

**Key Classes**:
- `TrafficTranslator`: Main application class that coordinates all components
- Manages configuration loading, component initialization, and message routing

**Responsibilities**:
- Initialize and start all protocol adapters with strict validation
- Route messages with **Command ID** tracking and lifecycle management
- Implement **State Aggregator** for centralized status lookups
- Handle system shutdown and cleanup
- Provide health monitoring via **Circuit Breaker** states
- Manage concurrent operations and failure isolation

**Configuration**: Reads YAML configuration file specifying adapters, translation rules, and system settings.

#### 2. Translation Engine (`traffic_translator/core/translation_engine.py`)

**Purpose**: Core logic for validating, optimizing, and routing traffic control commands.

**Key Classes**:
- `TranslationEngine`: Main translation logic
- `PhaseState`: Tracks current state of traffic phases
- `ValidationError`, `ConflictError`: Custom exceptions for error handling

**Features**:
- **Message Validation**: Ensures commands are safe and properly formatted
- **Conflict Detection**: Prevents conflicting phase commands (e.g., two greens simultaneously)
- **Safety Enforcement**: Enforces **Red Clearance Intervals** and valid phase sequences
- **Lifecycle Tracking**: Tracks commands through `PENDING`, `SENT`, `ACK`, `EXECUTING`, and `COMPLETED`.
- **Phase State Tracking**: Maintains current state of all traffic phases in coordination with the State Aggregator
- **History-Based Optimization**: Learns from command patterns to optimize future commands

**Validation Rules**:
- Maximum phase duration limits
- Minimum yellow light duration
- Priority level validation (0-2)
- Command type validation

#### 3. Message Format (`traffic_translator/core/message.py`)

**Purpose**: Defines the universal MQTT message format used throughout the system.

**Key Class**: `TrafficMessage` - Universal message format with the following structure:

```python
@dataclass
class TrafficMessage:
    command_id: str             # Unique UUID for lifecycle tracking
    timestamp: float
    controller_id: str
    message_type: str           # 'command', 'status', 'feedback', 'error'
    correlation_id: Optional[str] = None  # Links feedback to commands
    status: Optional[str] = None          # 'pending', 'sent', 'ack', 'failed', 'timeout'
    phase_id: Optional[str] = None
    command: Optional[str] = None         # 'green', 'yellow', 'red', 'flash', 'preempt'
    duration: Optional[int] = None
    priority: Optional[int] = None        # 0=normal, 1=high, 2=critical
    phase_status: Optional[Dict[str, Any]] = None
    detector_status: Optional[Dict[str, Any]] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    protocol_data: Optional[Dict[str, Any]] = None
```

**MQTT Topic Structure**:
- `traffic/{region}/{controller_id}/command/{phase_id}` - Send commands
- `traffic/{region}/{controller_id}/status` - Receive aggregated status
- `traffic/{region}/{controller_id}/feedback` - Receive sensor data
- `traffic/{region}/{controller_id}/error` - Error messages

#### 4. Decision Engine Interface (`traffic_translator/core/decision_engine_interface.py`)

**Purpose**: Integrates AI-powered or rule-based decision making for traffic control.

**Supported Engine Types**:
- **REST API Engines**: Cloud-based AI services
- **MQTT Engines**: Real-time decision services
- **Local Engines**: Rule-based or simple ML decisions

**Key Classes**:
- `DecisionEngineInterface`: Abstract base class
- `DecisionEngineManager`: Manages multiple engines with fallback logic
- `RESTDecisionEngine`, `MQTTDecisionEngine`, `LocalDecisionEngine`: Concrete implementations

**Fallback Logic**: Tries engines in configured order, falls back to next available engine if one fails.

#### 5. Feedback Listener (`traffic_translator/core/feedback_listener.py`)

**Purpose**: Handles real-time feedback from traffic controllers via SNMP traps and polling.

**Supported Feedback Sources**:
- **SNMP Traps**: NTCIP controllers sending asynchronous events
- **Modbus Polling**: PLC systems with periodic status checks

**Key Classes**:
- `FeedbackListener`: Main coordinator
- `FeedbackSource`: Abstract base for feedback sources
- `SNMPFeedbackSource`, `ModbusFeedbackSource`: Protocol-specific implementations

**Event Types**:
- `phase_change`: Phase status updates
- `detector_trigger`: Vehicle detection events
- `fault`: System fault notifications

## Protocol Adapters

### Base Adapter (`traffic_translator/adapters/base_adapter.py`)

**Purpose**: Abstract base class providing common functionality for all protocol adapters.

**Key Classes**:
- `BaseAdapter`: Abstract base with common adapter functionality
- `PollingAdapter`: For adapters that poll for status updates
- `EventDrivenAdapter`: For adapters that receive asynchronous events

**Common Features**:
- Connection management
- Message callback handling
- Health monitoring
- Statistics tracking
- Background task management

### MQTT Adapter (`traffic_translator/adapters/mqtt_adapter.py`)

**Purpose**: Serves as the central communication hub using MQTT protocol.

**Features**:
- Connects to MQTT broker as central hub
- Subscribes to regional traffic topics using regex-enforced patterns
- Validates topic structure: `traffic/([a-zA-Z0-9_-]+)/([a-zA-Z0-9_-]+)/([a-zA-Z0-9_-]+)`
- Publishes commands and receives status/feedback
- Asynchronous message processing with bounded queues
- QoS support and connection management

**Configuration**:
```yaml
mqtt_broker:
  type: mqtt
  connection:
    host: "localhost"
    port: 1883
    client_id: "traffic_translator_main"
```

### NTCIP Adapter (`traffic_translator/adapters/ntcip_adapter.py`)

**Purpose**: Communicates with traffic controllers using NTCIP 1202 standard via SNMP.

**Features**:
- SNMP GET/SET operations for phase control
- Polls phase status and detector data
- NTCIP OID mapping for traffic objects
- Fault monitoring and trap handling

**NTCIP Objects Supported**:
- Phase control (green/yellow/red/flash)
- Detector data (vehicle counts, presence)
- Timing parameters (min/max green, yellow duration)
- Fault monitoring
- Preemption control

**Configuration**:
```yaml
ntcip_controller_1:
  type: ntcip
  controller_id: intersection_1
  connection:
    host: "192.168.1.10"
    port: 161
    community: "public"
```

### Modbus Adapter (`traffic_translator/adapters/plc_adapter.py`)

**Purpose**: Integrates with PLC systems using Modbus TCP/RTU protocol.

**Features**:
- Read/write Modbus registers and coils
- Configurable register mapping
- Polling for status updates
- Support for both TCP and RTU connections

**Register Types**:
- Coils: Phase control outputs
- Holding Registers: Configuration and status
- Input Registers: Detector data

### GPIO Adapter (`traffic_translator/adapters/relay_adapter.py`)

**Purpose**: Controls traffic signals via direct GPIO pins (Raspberry Pi).

**Features**:
- Direct hardware control via GPIO pins
- Configurable pin mappings
- Relay switching for signal control
- Status monitoring via GPIO inputs

**Safety Features**:
- Conflict detection at hardware level
- Emergency stop capabilities
- Status feedback verification

### REST Adapter (`traffic_translator/adapters/rest_adapter.py`)

**Purpose**: Integrates with web services and REST APIs.

**Features**:
- HTTP GET/POST operations
- Authentication support (API keys, OAuth)
- Configurable endpoints
- JSON data exchange
- Error handling and retries

## NTCIP/SNMP Implementation (`traffic_translator/core/stmp_ntcip.py`)

**Purpose**: Provides NTCIP 1202 standard object definitions and mappings.

**Key Classes**:
- `NTCIP1202`: Core NTCIP object definitions and encoding/decoding
- `SNMPTrapDefinitions`: SNMP trap handling for events
- `NTCIPMessageMapper`: Bidirectional mapping between TrafficMessages and NTCIP objects

**NTCIP OIDs Supported**:
- Phase status and control
- Detector data and presence
- Timing parameters
- Fault monitoring
- Preemption control

**Trap Handling**:
- Phase change notifications
- Detector activations
- Fault conditions
- Preemption requests

## Configuration System

### Configuration File Structure

The system uses YAML configuration files with the following main sections:

```yaml
# Translation engine settings
translation:
  max_phase_duration: 300
  min_yellow_duration: 3
  preemption_enabled: true

# Decision engine configuration
decision_engine:
  fallback_order: [rest, local]
  engines:
    rest:
      type: rest
      base_url: "http://api.example.com"

# Feedback sources
feedback:
  sources:
    snmp_controller:
      type: snmp
      host: "192.168.1.100"

# Protocol adapters
adapters:
  mqtt_broker:
    type: mqtt
    connection:
      host: "localhost"
      port: 1883
  ntcip_controller:
    type: ntcip
    connection:
      host: "192.168.1.10"
```

### Configuration Validation

- Schema validation for configuration files
- Runtime validation of adapter connections
- Health checks for all components

## Testing Framework

### Test Structure

```
traffic_translator/test/
├── test_translation_engine.py    # Core translation logic tests
├── test_message_convertor.py     # Message conversion tests
├── test_message_history.py       # History tracking tests
├── test_bridge_client.py         # MQTT bridge tests
├── test_bridge.py               # Bridge functionality tests
└── test_*.py                    # Additional component tests
```

### Test Coverage

- Unit tests for all core components
- Integration tests for adapter communication
- Message format validation tests
- Conflict detection and resolution tests
- Performance and stress tests

## MQTT Translator (Legacy Component)

**Location**: `mqtt_translator/`

**Purpose**: Simple MQTT topic translator/bridge for basic message routing.

**Key Components**:
- `Bridge`: Main bridging logic between MQTT brokers
- `BridgeClient`: MQTT client with translation rules
- `PahoMqttClient`: Low-level MQTT client wrapper

**Features**:
- Topic-to-topic message translation
- Regular expression-based payload transformation
- Multi-broker bridging
- Cooldown periods to prevent message loops

**Note**: This is a simpler, separate component from the main traffic translator system.

## Dependencies

### Core Dependencies

- **PyYAML**: Configuration file parsing
- **paho-mqtt**: MQTT protocol support
- **pysnmp**: SNMP/NTCIP protocol support
- **pymodbus**: Modbus protocol support
- **RPi.GPIO**: GPIO hardware control
- **aiohttp**: REST API client
- **requests**: HTTP client fallback

### Development Dependencies

- **pytest**: Testing framework
- **pytest-asyncio**: Async testing support
- **mock**: Mocking for unit tests

## Deployment

### Docker Deployment

```dockerfile
FROM python:3.9-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
CMD ["python", "-m", "traffic_translator.main", "-c", "config.yaml"]
```

### System Requirements

- Python 3.8+
- Network access to traffic controllers
- MQTT broker (optional, can run embedded)
- Sufficient RAM for concurrent operations

### Production Considerations

- **Scalability**: Async I/O for high concurrency
- **Reliability**: Comprehensive error handling and retries
- **Monitoring**: Health checks and statistics
- **Security**: Authentication for MQTT and APIs
- **Logging**: Structured logging with configurable levels

## API Reference

### Command Line Interface

```bash
python -m traffic_translator.main -c config.yaml [-v|--verbose]
```

**Options**:
- `-c, --config`: Configuration file path (required)
- `-v, --verbose`: Increase verbosity (up to 3 levels)

### Programmatic API

```python
from traffic_translator.main import TrafficTranslator

# Initialize
translator = TrafficTranslator("config.yaml")
await translator.initialize()

# Start processing
await translator.start()

# Get status
status = translator.get_status()
```

## Troubleshooting

### Common Issues

1. **Adapter Connection Failures**
   - Check network connectivity
   - Verify protocol-specific credentials
   - Review firewall settings

2. **MQTT Message Routing Issues**
   - Verify topic patterns
   - Check QoS settings
   - Monitor broker connectivity

3. **Protocol Translation Errors**
   - Validate message formats
   - Check protocol-specific mappings
   - Review error logs

### Debugging

- Enable verbose logging: `python -m traffic_translator.main -c config.yaml -vvv`
- Check component health: Access health endpoints
- Monitor statistics: Review periodic status logs
- Test individual adapters: Use isolated test configurations

## Contributing

### Adding New Adapters

1. Create new adapter class inheriting from `BaseAdapter`
2. Implement required abstract methods
3. Add configuration parsing logic
4. Register adapter type in `main.py`
5. Add comprehensive tests
6. Update documentation

### Code Standards

- Type hints for all public methods
- Comprehensive docstrings
- Async/await for I/O operations
- Exception handling with specific error types
- Logging at appropriate levels

## License

MIT License - See LICENSE file for details.

## Acknowledgments

- Based on original MQTT Translator by Maarten Claes
- NTCIP 1202 standard implementation
- Open source community contributions