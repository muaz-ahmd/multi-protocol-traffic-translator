"""
Unit Tests for Traffic Translator Core Components
"""

import unittest
import asyncio
from unittest.mock import Mock, patch
from traffic_translator.core.message import TrafficMessage
from traffic_translator.core.translation_engine import TranslationEngine, ValidationError, ConflictError


class TestTrafficMessage(unittest.TestCase):
    """Test TrafficMessage functionality."""

    def test_create_command(self):
        """Test command message creation."""
        msg = TrafficMessage.create_command(
            controller_id="test_controller",
            phase_id="phase_1",
            command="green",
            duration=30
        )

        self.assertEqual(msg.controller_id, "test_controller")
        self.assertEqual(msg.phase_id, "phase_1")
        self.assertEqual(msg.command, "green")
        self.assertEqual(msg.duration, 30)
        self.assertEqual(msg.message_type, "command")

    def test_create_status(self):
        """Test status message creation."""
        msg = TrafficMessage.create_status(
            controller_id="test_controller",
            current_phase="phase_1",
            phase_status={"phase_1": "green"}
        )

        self.assertEqual(msg.message_type, "status")
        self.assertEqual(msg.current_phase, "phase_1")
        self.assertEqual(msg.phase_status, {"phase_1": "green"})

    def test_mqtt_conversion(self):
        """Test MQTT topic/payload conversion."""
        # Create message
        msg = TrafficMessage.create_command("controller1", "phase1", "green")

        # Convert to MQTT
        topic, payload = msg.to_mqtt()

        self.assertEqual(topic, "traffic/controller1/command/phase1")

        # Convert back from MQTT
        restored_msg = TrafficMessage.from_mqtt(topic, payload)

        self.assertEqual(restored_msg.controller_id, "controller1")
        self.assertEqual(restored_msg.phase_id, "phase1")
        self.assertEqual(restored_msg.command, "green")


class TestTranslationEngine(unittest.TestCase):
    """Test TranslationEngine functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.config = {
            'max_phase_duration': 300,
            'min_yellow_duration': 3,
            'preemption_enabled': True,
            'history_size': 10
        }
        self.engine = TranslationEngine(self.config)

    def test_validate_valid_command(self):
        """Test validation of valid command."""
        msg = TrafficMessage.create_command("test", "phase1", "green", duration=30)
        result = self.engine.validate_message(msg)
        self.assertTrue(result)

    def test_validate_invalid_command(self):
        """Test validation of invalid command."""
        msg = TrafficMessage.create_command("test", "phase1", "invalid_command")

        with self.assertRaises(ValidationError):
            self.engine.validate_message(msg)

    def test_validate_duration_too_long(self):
        """Test validation of duration exceeding maximum."""
        msg = TrafficMessage.create_command("test", "phase1", "green", duration=400)

        with self.assertRaises(ValidationError):
            self.engine.validate_message(msg)

    def test_yellow_duration_validation(self):
        """Test yellow light minimum duration."""
        msg = TrafficMessage.create_command("test", "phase1", "yellow", duration=1)

        with self.assertRaises(ValidationError):
            self.engine.validate_message(msg)

    def test_conflict_detection(self):
        """Test phase conflict detection."""
        # Set up conflicting phases
        self.engine.conflicting_phases = {"phase1": ["phase3"]}

        # Create message that should conflict
        msg1 = TrafficMessage.create_command("test", "phase1", "green")
        msg3 = TrafficMessage.create_command("test", "phase3", "green")

        # First message should be OK
        conflicts = self.engine.detect_conflicts(msg1)
        self.assertEqual(len(conflicts), 0)

        # Update state to show phase1 is active
        self.engine.update_phase_state(msg1)

        # Second message should conflict
        conflicts = self.engine.detect_conflicts(msg3)
        self.assertEqual(len(conflicts), 1)
        self.assertIn("conflicts with active phase", conflicts[0])

    def test_preemption_conflict(self):
        """Test preemption conflict when disabled."""
        self.engine.preemption_enabled = False

        msg = TrafficMessage.create_command("test", "phase1", "preempt")

        conflicts = self.engine.detect_conflicts(msg)
        self.assertEqual(len(conflicts), 1)
        self.assertIn("Preemption is disabled", conflicts[0])

    def test_process_message(self):
        """Test complete message processing."""
        msg = TrafficMessage.create_command("test", "phase1", "green", duration=30)

        processed = self.engine.process_message(msg)

        # Should have default priority set
        self.assertEqual(processed.priority, 0)

        # Should be in history
        self.assertEqual(len(self.engine.command_history), 1)

    def test_phase_state_tracking(self):
        """Test phase state tracking."""
        # Send command
        msg = TrafficMessage.create_command("test", "phase1", "green", duration=30)
        self.engine.update_phase_state(msg)

        # Check state
        states = self.engine.get_phase_states()
        self.assertIn("phase1", states)
        self.assertEqual(states["phase1"]["command"], "green")
        self.assertEqual(states["phase1"]["duration_remaining"], 30)


class TestValidationError(unittest.TestCase):
    """Test custom exception classes."""

    def test_validation_error(self):
        """Test ValidationError exception."""
        error = ValidationError("Test error")
        self.assertEqual(str(error), "Test error")

    def test_conflict_error(self):
        """Test ConflictError exception."""
        error = ConflictError("Test conflict")
        self.assertEqual(str(error), "Test conflict")


if __name__ == '__main__':
    unittest.main()