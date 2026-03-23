# Traffic Translator — Usage Guide

A multi-protocol translation layer for smart traffic signal controllers.  
MQTT acts as the central lingua franca between an ML decision engine, YOLO input, and fieldside controllers speaking **NTCIP/SNMP**, **Modbus/PLC**, **GPIO/Relay**, or **REST**.

---

## Table of Contents

1. [Installation](#installation)
2. [Quick Start](#quick-start)
3. [Configuration](#configuration)
   - [Translation Engine](#translation-engine)
   - [Decision Engine](#decision-engine)
   - [Feedback Listener](#feedback-listener)
   - [Protocol Adapters](#protocol-adapters)
   - [Logging & System](#logging--system)
4. [Architecture Overview](#architecture-overview)
5. [MQTT Topic Structure](#mqtt-topic-structure)
6. [Message Format](#message-format)
7. [Extending the System](#extending-the-system)
8. [Resilience Features](#resilience-features)
9. [Troubleshooting](#troubleshooting)

---

## Installation

```bash
# Clone
git clone <repo-url>
cd multi-protocol-traffic-translator

# Virtual environment (recommended)
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Dependency Notes

| Package | Needed for | When to skip |
|---|---|---|
| `pysnmp>=6.0` | NTCIP/SNMP adapters | No NTCIP controllers |
| `pymodbus>=3.0` | Modbus PLC adapters | No PLCs |
| `RPi.GPIO>=0.7` | GPIO relay control | Not on Raspberry Pi |
| `paho-mqtt>=1.6` | Core MQTT hub | Always required |
| `pydantic>=2.0` | Config validation | Always required |
| `aiohttp>=3.8` | REST adapter | No REST controllers |
| `PyYAML>=6.0` | Config parsing | Always required |

---

## Quick Start

```bash
# 1. Copy the example config
cp traffic_translator/config/traffic_controller_example.yaml my_config.yaml

# 2. Edit my_config.yaml with your controller details

# 3. Run the translator
python -m traffic_translator.main -c my_config.yaml

# With verbose logging (up to -vvv)
python -m traffic_translator.main -c my_config.yaml -vv
```

The translator will:
1. Parse and validate your YAML against Pydantic schemas (crashes early if invalid)
2. Initialize all enabled adapters
3. Connect to the MQTT broker (central hub)
4. Connect to each configured controller
5. Begin routing messages between protocols

**Stop gracefully** with `Ctrl+C` or `SIGTERM`.

---

## Configuration

All configuration lives in a single YAML file. See [`traffic_controller_example.yaml`](traffic_translator/config/traffic_controller_example.yaml) for a complete reference.

### Translation Engine

Controls how commands are validated and phase conflicts are resolved.

```yaml
translation:
  max_phase_duration: 300    # Max seconds any phase can stay active
  min_yellow_duration: 3     # MUTCD-compliant yellow minimum
  preemption_enabled: true   # Allow emergency preemption
  history_size: 100          # Number of past commands to retain

  default_durations:         # Seconds per command type
    green: 45
    yellow: 5
    red: 30
    flash: 10

  conflicting_phases:        # Phases that MUST NOT be green simultaneously
    phase_1: [phase_3]
    phase_2: [phase_4]
```

> **Safety**: The translation engine will reject any command that would put two conflicting phases in `green` at the same time.

---

### Decision Engine

Configures the ML / rule-based decision pipeline. Engines are tried concurrently — the response with the **highest confidence score** wins.

```yaml
decision_engine:
  fallback_order: [rest, local]   # Which engines to query

  engines:
    rest:
      type: rest                   # REST API (e.g. your ML model server)
      base_url: "http://localhost:8080/api"
      api_key: "your-api-key"
      timeout: 5.0

    local:
      type: local                  # Local rule engine
      rules:
        - name: "traffic_adaptive"
          condition: "vehicle_count > 10"
          action: "extend_green"
```

| Engine Type | Description |
|---|---|
| `rest` | Calls an external REST endpoint for decisions |
| `local` | Evaluates simple rules locally |
| `mqtt` | Listens on an MQTT topic for AI decisions |

---

### Feedback Listener

Receives real-time data from field sensors for loop detectors, pedestrian buttons, etc.

```yaml
feedback:
  sources:
    snmp_traps:
      type: snmp
      host: "192.168.1.100"
      port: 162
      community: "public"

    modbus_polling:
      type: modbus
      protocol: tcp
      host: "192.168.1.101"
      port: 502
      unit_id: 1
      poll_interval: 2.0
```

---

### Protocol Adapters

Each adapter bridges a specific field protocol to the central MQTT bus.

#### MQTT (Central Hub)

```yaml
adapters:
  mqtt_broker:
    type: mqtt
    enabled: true
    controller_id: central_hub
    connection:
      host: "localhost"
      port: 1883
      client_id: "traffic_translator_main"
      keepalive: 60
    topics:
      command: "traffic/+/command/+"
      status: "traffic/+/status/+"
      feedback: "traffic/+/feedback/+"
      error: "traffic/+/error"
```

#### NTCIP/SNMP

```yaml
  ntcip_controller_1:
    type: ntcip
    enabled: true
    controller_id: intersection_1
    polling_interval: 5.0        # Status poll every 5s
    connection:
      host: "192.168.1.10"
      port: 161
      community: "public"
      timeout: 5
      retries: 3
    mapping:
      phase_count: 8
      detector_count: 16
```

#### Modbus/PLC

```yaml
  plc_controller_1:
    type: modbus
    enabled: true
    controller_id: plc_1
    polling_interval: 2.0
    connection:
      protocol: tcp              # or 'rtu' for serial
      host: "192.168.1.11"
      port: 502
      unit_id: 1
      timeout: 5.0
    mapping:
      register_map:
        phase_control:
          address: 1000
          count: 8
          type: coil
        phase_status:
          address: 1100
          count: 8
          type: holding
        detector_data:
          address: 1200
          count: 16
          type: input
```

#### GPIO (Raspberry Pi)

```yaml
  gpio_controller_1:
    type: gpio
    enabled: true
    controller_id: gpio_1
    polling_interval: 1.0
    connection:
      gpio_mode: BCM
      pin_mapping:
        phase_1_red: 17
        phase_1_yellow: 18
        phase_1_green: 27
```

#### REST API

```yaml
  rest_api_1:
    type: rest
    enabled: true
    controller_id: api_1
    polling_interval: 10.0
    connection:
      base_url: "http://api.traffic-controller.com"
      api_key: "your-api-key"
      timeout: 10.0
    mapping:
      endpoints:
        status: "/v1/status"
        command: "/v1/command"
```

### Logging & System

```yaml
logging:
  level: INFO                    # DEBUG | INFO | WARNING | ERROR
  format: "%(asctime)s %(name)s %(levelname)s: %(message)s"
  file: "traffic_translator.log" # null = stdout only

system:
  max_concurrent_commands: 10    # Concurrent dispatch limit
  command_timeout: 30            # Per-command timeout (seconds)
  health_check_interval: 60     # Health poll interval (seconds)
```

---

## Architecture Overview

```
┌──────────────┐     ┌────────────────────────────────────────┐     ┌──────────────┐
│  ML Model    │     │          Traffic Translator             │     │  NTCIP       │
│  (YOLO etc.) │────▶│                                        │────▶│  Controller  │
└──────────────┘     │  ┌──────────┐    ┌──────────────────┐  │     └──────────────┘
                     │  │ MQTT Hub │◀──▶│ Translation Engine│  │
┌──────────────┐     │  │ (central)│    │ (validation +     │  │     ┌──────────────┐
│  Decision    │────▶│  └──────────┘    │  conflict detect) │  │────▶│  Modbus PLC  │
│  Engine API  │     │                  └──────────────────┘  │     └──────────────┘
└──────────────┘     │  ┌──────────┐    ┌──────────────────┐  │
                     │  │ Adapter  │    │  Circuit Breaker  │  │     ┌──────────────┐
┌──────────────┐     │  │ Registry │    │  (per adapter)    │  │────▶│  GPIO Relay  │
│  Feedback    │────▶│  └──────────┘    └──────────────────┘  │     └──────────────┘
│  Sensors     │     │                                        │
└──────────────┘     └────────────────────────────────────────┘     ┌──────────────┐
                                                                ────▶│  REST API    │
                                                                    └──────────────┘
```

**Data flow**: Incoming MQTT commands → TranslationEngine validates → fan-out via `asyncio.gather` to target adapters → adapter converts to native protocol → controller executes.

---

## MQTT Topic Structure

All internal messaging follows this topic convention:

```
traffic/{controller_id}/{message_type}/{phase_id}
```

| Segment | Values | Example |
|---|---|---|
| `controller_id` | Any string identifier | `intersection_1` |
| `message_type` | `command`, `status`, `feedback`, `error` | `command` |
| `phase_id` | `phase_1` … `phase_N` (optional) | `phase_3` |

**Examples**:
```
traffic/intersection_1/command/phase_1    → Send green to phase 1
traffic/plc_1/status/phase_3             → Status of phase 3 on PLC
traffic/central_hub/error                → Error notification
```

---

## Message Format

Every message flowing through the system uses the `TrafficMessage` dataclass. The JSON payload:

```json
{
  "timestamp": 1711223344.567,
  "controller_id": "intersection_1",
  "message_type": "command",
  "phase_id": "phase_1",
  "command": "green",
  "duration": 45,
  "priority": 0
}
```

### Message Types

| Type | Fields | Description |
|---|---|---|
| `command` | `phase_id`, `command`, `duration`, `priority` | Phase control (green/yellow/red/flash/preempt) |
| `status` | `current_phase`, `phase_status`, `detector_status` | Controller status poll |
| `feedback` | `phase_id`, `detector_status` | Sensor data from the field |
| `error` | `error_code`, `error_message` | Fault notifications |

### Sending a Command via MQTT

Publish to the broker to send a command to any connected controller:

```bash
# Turn phase 1 green for 45 seconds on intersection_1
mosquitto_pub -h localhost -t "traffic/intersection_1/command/phase_1" \
  -m '{"command":"green","duration":45,"priority":0,"timestamp":0}'
```

### Programmatic Usage

```python
from traffic_translator.core.message import TrafficMessage

# Create a command
msg = TrafficMessage.create_command(
    controller_id="intersection_1",
    phase_id="phase_1",
    command="green",
    duration=45,
    priority=0
)

# Serialize for MQTT
topic, payload = msg.to_mqtt()
# topic  = "traffic/intersection_1/command/phase_1"
# payload = b'{"timestamp": ..., "command": "green", ...}'
```

---

## Extending the System

### Adding a New Protocol Adapter

1. Create a new file in `traffic_translator/adapters/`:

```python
from .base_adapter import PollingAdapter  # or EventDrivenAdapter
from ..config.models import AdapterModel

class MyAdapter(PollingAdapter):
    def __init__(self, name: str, config: AdapterModel):
        super().__init__(name, config)
        # Read custom params from config.connection_params

    async def connect(self) -> bool: ...
    async def disconnect(self): ...
    async def send_command(self, message) -> bool: ...
    async def request_status(self): ...
    def is_connected(self) -> bool: ...
```

2. Register it in `main.py`:

```python
from .adapters.my_adapter import MyAdapter
AdapterRegistry.register('my_protocol', MyAdapter)
```

3. Add to your YAML config:

```yaml
adapters:
  my_device:
    type: my_protocol
    enabled: true
    controller_id: device_1
    connection:
      host: "192.168.1.50"
```

That's it — the registry handles instantiation automatically.

### Adding a New Decision Engine

Implement `DecisionEngineInterface`:

```python
class MyEngine(DecisionEngineInterface):
    async def request_decision(self, request): ...
    def is_available(self) -> bool: ...
```

Add it to `_initialize_engines()` in `DecisionEngineManager` and include its name in `fallback_order`.

---

## Resilience Features

### Circuit Breaker

Every adapter has a built-in circuit breaker. Use `send_command_safe()` instead of `send_command()` for automatic protection:

| State | Behavior |
|---|---|
| **CLOSED** | Normal operation. Failures increment a counter. |
| **OPEN** | After 5 consecutive failures — all calls rejected for 30s. |
| **HALF_OPEN** | After cooldown — one probe request allowed. Success resets, failure reopens. |

### Bounded Queues

The MQTT adapter uses `asyncio.Queue(maxsize=1000)`. When full, new messages are **dropped** (not blocked), preventing OOM under burst load.

### Background Cleanup

A background task runs every 5 minutes to sweep expired phase states from the translation engine, preventing memory leaks from stale data.

---

## Troubleshooting

| Issue | Cause | Fix |
|---|---|---|
| `pydantic.ValidationError` at startup | Invalid YAML config | Check field types match the schema in `config/models.py` |
| `SNMP connection failed` | Wrong host/community | Verify SNMP access: `snmpget -v2c -c public <host> 1.3.6.1.2.1.1.1.0` |
| `Modbus test read failed` | Wrong unit ID or register | Check PLC docs for correct slave ID and register addresses |
| `Circuit breaker OPEN` in logs | 5+ consecutive failures | Controller may be offline; breaker auto-retries after 30s |
| `Queue full, dropping message` | Burst exceeds 1000 msgs | Increase `maxsize` or reduce publish rate |
| `No decision engines available` | All engines unreachable | Check `base_url` / connectivity for REST engine |

### Useful Commands

```bash
# Monitor all MQTT traffic
mosquitto_sub -h localhost -t "traffic/#" -v

# Check SNMP connectivity
snmpget -v2c -c public 192.168.1.10 1.3.6.1.2.1.1.1.0

# Test Modbus connectivity
pymodbus.console tcp --host 192.168.1.11 --port 502
```
