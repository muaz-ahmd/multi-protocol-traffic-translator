# Multi-Protocol Traffic Translator

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)

A production-ready, multi-protocol traffic signal controller system that translates and routes commands/feedback across MQTT, NTCIP/SNMP, Modbus/PLC, GPIO Relay, and REST API protocols.

## 🚦 Overview

The Traffic Translator serves as a universal communication hub for traffic signal controllers, enabling seamless integration between different protocols and systems. MQTT serves as the central interchange language, with automatic translation to/from protocol-specific formats.

### Key Features

✅ **Multi-Protocol Support**: MQTT, NTCIP 1202, Modbus TCP/RTU, GPIO Relay, REST API
✅ **Command Lifecycle Tracking**: Unique `command_id` tracking from PENDING to COMPLETED/FAILED
✅ **State Aggregator**: Centralized source of truth for all controller states
✅ **Safety Enforcement**: Strict Red Clearance Intervals and phase transition validation
✅ **Strict MQTT Validation**: Regex-enforced topic structures for region/controller isolation
✅ **Resilience & Isolation**: Exponential backoff retries, Circuit Breakers, and adapter isolation
✅ **Structured Logging**: Machine-readable JSON logs for easy trace correlation
✅ **Production Ready**: Docker support, comprehensive Pydantic validation

## 🏗️ Architecture

```
Cloud Layer (Analytics/Dashboard)
    ↓
Decision Engine (Rules/AI/Priority)
    ↓
State Aggregator (Global State Sync)
    ↓
Translation Engine (Safety Rules + Validation)
    ↓ (4 routes)
NTCIP Adapter | Modbus Adapter | GPIO Adapter | REST Adapter
    ↓ (isolated tasks with retries/circuit breakers)
Traffic Ctrl  | PLC System     | Relay Board  | Smart API
    ↓
Feedback Listener (SNMP Traps + Polling)
    ↓ (updates State Aggregator)
MQTT Hub → Cloud Analytics
```

## 🚀 Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/your-org/traffic-translator.git
cd traffic-translator

# Install dependencies
pip install -r requirements.txt

# Or install as package
pip install -e .
```

### Basic Usage

1. **Copy configuration**:
   ```bash
   cp traffic_translator/config/traffic_controller_example.yaml traffic_translator/config/my_config.yaml
   ```

2. **Edit configuration** for your setup (see Configuration section below)

3. **Run the translator**:
   ```bash
   python -m traffic_translator.main -c traffic_translator/config/my_config.yaml
   ```

4. **Send commands via MQTT**:
   ```bash
   # Example: Turn phase 1 green for 30 seconds on intersection_1 in region 'north'
   mosquitto_pub -t "traffic/north/intersection_1/command/phase_1" \
     -m '{"command": "green", "duration": 30, "priority": 0}'
   ```

## 📋 Configuration

The system is configured via YAML files. See `traffic_translator/config/traffic_controller_example.yaml` for a complete example.

### Basic Configuration Structure

```yaml
# Translation Engine Settings
translation:
  max_phase_duration: 300
  min_yellow_duration: 3
  preemption_enabled: true

# Decision Engine (optional)
decision_engine:
  fallback_order: [rest, local]
  engines:
    rest:
      type: rest
      base_url: "http://your-decision-api.com"

# Feedback Sources
feedback:
  sources:
    snmp_controller:
      type: snmp
      host: "192.168.1.100"

# Protocol Adapters
adapters:
  mqtt_broker:
    type: mqtt
    connection:
      host: "localhost"
      port: 1883

  ntcip_controller:
    type: ntcip
    controller_id: intersection_1
    connection:
      host: "192.168.1.10"
```

### Supported Protocols

#### MQTT (Central Hub)
- **Purpose**: Universal interchange format
- **Configuration**: Broker connection, topics, QoS settings

#### NTCIP 1202 (Traffic Controllers)
- **Purpose**: Standard traffic signal communication
- **Features**: SNMP GET/SET, trap handling, phase control
- **Dependencies**: `pysnmp`

#### Modbus TCP/RTU (PLC Systems)
- **Purpose**: Industrial controller integration
- **Features**: Register reading/writing, coil control
- **Dependencies**: `pymodbus`

#### GPIO Relay (Raspberry Pi)
- **Purpose**: Direct hardware control
- **Features**: Pin control, relay switching
- **Dependencies**: `RPi.GPIO`

#### REST API
- **Purpose**: Web service integration
- **Features**: HTTP GET/POST, authentication
- **Dependencies**: `aiohttp`

## 🔧 API Reference

### TrafficMessage Format

All communication uses standardized MQTT messages:

```python
# Command Message
{
  "command_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": 1640995200.0,
  "controller_id": "intersection_1",
  "message_type": "command",
  "phase_id": "phase_1",
  "command": "green",
  "duration": 30,
  "priority": 0
}

# Status Message (Centralized via State Aggregator)
{
  "timestamp": 1640995200.0,
  "controller_id": "intersection_1",
  "message_type": "status",
  "status": "active",
  "phase_status": {"phase_1": "green", "phase_2": "red"}
}

# Feedback Message
{
  "timestamp": 1640995200.0,
  "controller_id": "intersection_1",
  "message_type": "feedback",
  "phase_id": "detector_1",
  "detector_status": {"vehicle_count": 15}
}
```

### MQTT Topics

- `traffic/{region}/{controller_id}/command/{phase_id}` - Send commands
- `traffic/{region}/{controller_id}/status` - Receive aggregated status
- `traffic/{region}/{controller_id}/feedback` - Receive sensor data
- `traffic/{region}/{controller_id}/error` - Fault notifications

## 🧪 Testing

Run the test suite:

```bash
python -m pytest traffic_translator/test/
```

Run specific tests:

```bash
python -m pytest traffic_translator/test/test_translation_engine.py -v
```

## 🐳 Docker Deployment

Build and run with Docker:

```bash
# Build image
docker build -t traffic-translator .

# Run with configuration
docker run -v $(pwd)/config:/config traffic-translator -c /config/my_config.yaml
```

### Docker Compose

```yaml
version: '3.8'
services:
  traffic-translator:
    build: .
    volumes:
      - ./config:/config
    command: ["-c", "/config/traffic_controller.yaml"]
    ports:
      - "1883:1883"  # If running MQTT broker
```

## 📚 Examples

See `traffic_translator/examples/` for usage examples:

- `simple_phase_control.py` - Basic signal control
- `preemption_example.py` - Emergency vehicle handling
- `decision_engine_integration.py` - AI integration

## 🔍 Monitoring & Debugging

### Logging

Configure logging levels in your configuration:

```yaml
logging:
  level: DEBUG
  format: "%(asctime)s %(name)s %(levelname)s: %(message)s"
```

### Health Checks

The system provides health check endpoints for all adapters and feedback sources.

### Troubleshooting

Common issues:

1. **Adapter not connecting**: Check network connectivity and credentials
2. **MQTT messages not routing**: Verify topic patterns and QoS settings
3. **Protocol translation failing**: Check message format and validation rules

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit a pull request

### Adding New Adapters

1. Create new adapter class inheriting from `BaseAdapter`
2. Implement required abstract methods
3. Add configuration parsing
4. Update `AdapterFactory` in `main.py`
5. Add dependencies to `requirements.txt`

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Based on the original MQTT Translator by Maarten Claes
- NTCIP 1202 standard implementation
- Open source community contributions

## 📞 Support

For questions and support:

- Open an issue on GitHub
- Check the documentation in `docs/`
- Review example configurations

### Regular expression

Matches MQTT message by *topic_search* and *payload_search* expressions (https://docs.python.org/3/library/re.html). Renders *topic_template* and *payload_template* by using the found regexp groups.

With *[topic.1]* and *[topic.99]* in your template, the first and 99th group from the *topic_search* expression will be substituted. This works the same for payload with *[payload.x]*.

A template will substitute only the found part. So, remaining pre- and/or suffixes will stay.

In case no search was done (topic_search or payload_search missing) but a template is supplied, it will replace the whole topic or payload.

*Example config:*

```yaml
regexp:
  - topic_search: temp/(auto)
    payload_search: (heat) (\d+)
    topic_template: temp/[payload.1]
    payload_template: [payload.2] - [topic.1]
  - ...
```

*Example with result:*

```yaml
regexp:
  - payload_search: (\w+)|(\d+)|(\w+)
    topic_template: house/[payload.1]/temperature
    payload_template: [payload.2] [payload.3]
  - ...
```
| | Topic | Payload |
| --- | --- | --- |
| Original | house/87946548/auto | bedroom,24,auto |
| Translated | house/bedroom/temperature | 24 auto |

### Set retain

Set retain flag of a message.
Messages are matching on topic by using a RE fullmatch expression (see https://docs.python.org/3/library/re.html#re.fullmatch)

*Example config:*

```yaml
set_retain:
  - topic_fullsearch: .*temp
    retain: True
  - ...
```

## Examples

### Bridging with space replacement

```yaml
source:
  id: MQTT-Translator-Source
  host: source_mqttbroker
  port: 1883
  keepalive_interval: 60
  topics:
    - world/#
  publish:
    cooldown: 2
    convert:
      - topic:
        - from: '_' 
          to: ' '
target:
  id: MQTT-Translator-Target
  host: target_mqttbroker
  port: 1883
  keepalive_interval: 60
  topics:
    - world/#
  publish:
    cooldown: 2
    convert:
      - topic:
        - from: ' ' 
          to: '_'
```

### Topic replace

```yaml
source:
  id: MQTT-Translator-Source
  host: mqttbroker
  port: 1883
  keepalive_interval: 60
  topics:
    - 1235332/#
  publish:
    cooldown: 2
    convert:
      - topic:
        - from: '1235332' 
          to: 'temp_sensor'
target:
  id: MQTT-Translator-Target
  host: mqttbroker
  port: 1883
  keepalive_interval: 60
  topics:
  publish:
    cooldown: 2
    convert:
      - topic:
        - from: '1235332' 
          to: 'temp_sensor'
```