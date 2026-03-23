#!/usr/bin/env python3
"""
Simple Phase Control Example

Demonstrates basic traffic signal control using the Traffic Translator.
"""

import asyncio
import logging
from traffic_translator.core.message import TrafficMessage
from traffic_translator.adapters.mqtt_adapter import MQTTAdapter
from traffic_translator.adapters.base_adapter import AdapterConfig


async def simple_phase_control():
    """Demonstrate basic phase control commands."""

    # Setup logging
    logging.basicConfig(level=logging.INFO)

    # Create MQTT adapter for communication
    mqtt_config = AdapterConfig(
        name="example_mqtt",
        type="mqtt",
        controller_id="example_controller",
        connection_params={
            "host": "localhost",
            "port": 1883,
            "client_id": "phase_control_example"
        }
    )

    mqtt_adapter = MQTTAdapter(mqtt_config)

    # Set up message handler
    def on_message(message: TrafficMessage):
        print(f"Received: {message}")

    mqtt_adapter.set_message_callback(on_message)

    try:
        # Start adapter
        await mqtt_adapter.connect()
        await mqtt_adapter.start()

        print("Traffic Translator Phase Control Example")
        print("========================================")

        # Example 1: Basic green command
        print("\n1. Sending green command to phase 1...")
        green_command = TrafficMessage.create_command(
            controller_id="example_controller",
            phase_id="phase_1",
            command="green",
            duration=30
        )
        await mqtt_adapter.send_command(green_command)

        await asyncio.sleep(2)

        # Example 2: Yellow command
        print("\n2. Sending yellow command to phase 1...")
        yellow_command = TrafficMessage.create_command(
            controller_id="example_controller",
            phase_id="phase_1",
            command="yellow",
            duration=5
        )
        await mqtt_adapter.send_command(yellow_command)

        await asyncio.sleep(2)

        # Example 3: Red command
        print("\n3. Sending red command to phase 1...")
        red_command = TrafficMessage.create_command(
            controller_id="example_controller",
            phase_id="phase_1",
            command="red",
            duration=30
        )
        await mqtt_adapter.send_command(red_command)

        await asyncio.sleep(2)

        # Example 4: Status request (would be sent to appropriate adapter)
        print("\n4. Requesting status...")
        # Note: In real usage, this would go to the specific controller adapter

        print("\nExample completed. Check MQTT broker for messages.")

    except KeyboardInterrupt:
        print("\nInterrupted by user")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await mqtt_adapter.stop()


async def preemption_example():
    """Demonstrate emergency vehicle preemption."""

    print("\nEmergency Vehicle Preemption Example")
    print("===================================")

    # High-priority preemption command
    preemption_command = TrafficMessage.create_command(
        controller_id="intersection_main",
        phase_id="phase_emergency",
        command="preempt",
        duration=60,
        priority=2  # Critical priority
    )

    print(f"Preemption command: {preemption_command}")

    # In a real system, this would be sent through the MQTT adapter
    # await mqtt_adapter.send_command(preemption_command)


async def decision_engine_integration():
    """Demonstrate decision engine integration."""

    print("\nDecision Engine Integration Example")
    print("==================================")

    # Simulate detector data for decision making
    detector_message = TrafficMessage.create_feedback(
        controller_id="intersection_main",
        phase_id="phase_1",
        detector_status={
            "vehicle_count": 15,
            "wait_time": 45,
            "emergency_vehicle": False
        }
    )

    print(f"Detector feedback: {detector_message}")

    # Decision engine would process this and send commands
    # In real usage, the decision engine would receive this data
    # and respond with optimized timing commands


if __name__ == "__main__":
    print("Traffic Translator Examples")
    print("==========================")

    # Run basic phase control example
    asyncio.run(simple_phase_control())

    # Show other examples
    asyncio.run(preemption_example())
    asyncio.run(decision_engine_integration())