"""
MQTT Adapter for Traffic Controllers

Enhanced MQTT client that serves as the central communication hub for the traffic translator.
"""

import logging
import asyncio
import json
from typing import Dict, Any, Optional, List, Callable

try:
    import paho.mqtt.client as mqtt
    PAHO_MQTT_AVAILABLE = True
except ImportError:
    PAHO_MQTT_AVAILABLE = False

from .base_adapter import BaseAdapter, AdapterConfig, EventDrivenAdapter
from ..core.message import TrafficMessage


class MQTTAdapter(EventDrivenAdapter):
    """
    MQTT adapter for traffic signal control.

    Serves as the central communication hub, translating between MQTT messages
    and other protocol adapters.
    """

    def __init__(self, config: AdapterConfig):
        super().__init__(config)

        # MQTT configuration
        conn_params = config.connection_params or {}
        self.host = conn_params.get('host', 'localhost')
        self.port = conn_params.get('port', 1883)
        self.keepalive = conn_params.get('keepalive', 60)
        self.client_id = conn_params.get('client_id', f"traffic_translator_{config.name}")

        # Authentication
        self.username = conn_params.get('username')
        self.password = conn_params.get('password')

        # Topics
        self.topic_config = conn_params.get('topics', {
            'command': 'traffic/+/command/+',  # traffic/{controller}/command/{phase}
            'status': 'traffic/+/status/+',    # traffic/{controller}/status/{phase}
            'feedback': 'traffic/+/feedback/+', # traffic/{controller}/feedback/{phase}
            'error': 'traffic/+/error',        # traffic/{controller}/error
        })

        # MQTT client
        self.client = None

        # Message queues
        self._incoming_queue = asyncio.Queue()
        self._outgoing_queue = asyncio.Queue()

        # Statistics
        self._messages_sent = 0
        self._messages_received = 0
        self._error_count = 0

    async def connect(self) -> bool:
        """
        Establish MQTT connection.

        Returns:
            True if connection successful
        """
        if not PAHO_MQTT_AVAILABLE:
            self.logger.error("paho-mqtt not available. Install with: pip install paho-mqtt")
            return False

        try:
            self.logger.info(f"Connecting to MQTT broker at {self.host}:{self.port}")

            # Create MQTT client
            self.client = mqtt.Client(client_id=self.client_id, clean_session=True)

            # Set authentication
            if self.username and self.password:
                self.client.username_pw_set(self.username, self.password)

            # Set callbacks
            self.client.on_connect = self._on_connect
            self.client.on_disconnect = self._on_disconnect
            self.client.on_message = self._on_message

            # Connect
            self.client.connect(self.host, self.port, self.keepalive)

            # Start network loop in background thread
            self.client.loop_start()

            # Wait for connection
            timeout = 10
            start_time = asyncio.get_event_loop().time()

            while not self.client.is_connected() and (asyncio.get_event_loop().time() - start_time) < timeout:
                await asyncio.sleep(0.1)

            if not self.client.is_connected():
                self.logger.error("MQTT connection timeout")
                return False

            self._connected = True
            self.logger.info(f"Successfully connected to MQTT broker as {self.client_id}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to connect to MQTT broker: {e}")
            return False

    async def disconnect(self):
        """Disconnect from MQTT broker."""
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
        self._connected = False
        self.logger.info("Disconnected from MQTT broker")

    async def send_command(self, message: TrafficMessage) -> bool:
        """
        Send command message via MQTT.

        Args:
            message: Command message to send

        Returns:
            True if message published successfully
        """
        if not self._validate_message_for_adapter(message):
            return False

        try:
            # Put message in outgoing queue
            await self._outgoing_queue.put(message)
            return True

        except Exception as e:
            self.logger.error(f"Failed to queue MQTT message: {e}")
            self._error_count += 1
            return False

    async def request_status(self) -> Optional[TrafficMessage]:
        """
        Request status via MQTT (not typically used for MQTT adapter).

        Returns:
            None (MQTT adapter doesn't poll for status)
        """
        return None

    def is_connected(self) -> bool:
        """Check MQTT connection status."""
        return self._connected and self.client and self.client.is_connected()

    async def _event_loop(self):
        """Main event loop for processing MQTT messages."""
        try:
            while self._connected:
                # Process incoming messages
                try:
                    message = self._incoming_queue.get_nowait()
                    if self._message_callback:
                        self._message_callback(message)
                    self._messages_received += 1
                except asyncio.QueueEmpty:
                    pass

                # Process outgoing messages
                try:
                    message = self._outgoing_queue.get_nowait()
                    await self._publish_message(message)
                    self._messages_sent += 1
                except asyncio.QueueEmpty:
                    pass

                await asyncio.sleep(0.01)  # Small delay to prevent busy loop

        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.logger.error(f"Error in MQTT event loop: {e}")

    def _on_connect(self, client, userdata, flags, rc):
        """MQTT connect callback."""
        if rc == 0:
            self.logger.info("MQTT connected successfully")

            # Subscribe to topics
            for topic_type, topic_pattern in self.topic_config.items():
                try:
                    client.subscribe(topic_pattern)
                    self.logger.debug(f"Subscribed to {topic_pattern}")
                except Exception as e:
                    self.logger.error(f"Failed to subscribe to {topic_pattern}: {e}")
        else:
            self.logger.error(f"MQTT connection failed with code {rc}")

    def _on_disconnect(self, client, userdata, rc):
        """MQTT disconnect callback."""
        self.logger.warning(f"MQTT disconnected with code {rc}")
        self._connected = False

    def _on_message(self, client, userdata, msg):
        """MQTT message callback."""
        try:
            # Convert MQTT message to TrafficMessage
            message = TrafficMessage.from_mqtt(msg.topic, msg.payload)

            # Put in incoming queue
            asyncio.create_task(self._incoming_queue.put(message))

        except Exception as e:
            self.logger.error(f"Failed to process MQTT message: {e}")
            self._error_count += 1

    async def _publish_message(self, message: TrafficMessage):
        """Publish TrafficMessage to MQTT."""
        try:
            topic, payload = message.to_mqtt()

            # Publish with QoS 1 for reliability
            result = self.client.publish(topic, payload, qos=1)

            # Wait for publish to complete (optional)
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                self.logger.error(f"MQTT publish failed: {result.rc}")

        except Exception as e:
            self.logger.error(f"Failed to publish MQTT message: {e}")
            self._error_count += 1

    def subscribe_to_topics(self, topics: List[str]):
        """Subscribe to additional topics."""
        if not self.client or not self.client.is_connected():
            return

        for topic in topics:
            try:
                self.client.subscribe(topic)
                self.logger.debug(f"Subscribed to additional topic: {topic}")
            except Exception as e:
                self.logger.error(f"Failed to subscribe to {topic}: {e}")

    def unsubscribe_from_topics(self, topics: List[str]):
        """Unsubscribe from topics."""
        if not self.client or not self.client.is_connected():
            return

        for topic in topics:
            try:
                self.client.unsubscribe(topic)
                self.logger.debug(f"Unsubscribed from topic: {topic}")
            except Exception as e:
                self.logger.error(f"Failed to unsubscribe from {topic}: {e}")

    async def publish_raw(self, topic: str, payload: str, qos: int = 1):
        """
        Publish raw MQTT message.

        Args:
            topic: MQTT topic
            payload: Message payload
            qos: Quality of Service level
        """
        if not self.client or not self.client.is_connected():
            return

        try:
            result = self.client.publish(topic, payload, qos=qos)
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                self.logger.error(f"Raw MQTT publish failed: {result.rc}")
        except Exception as e:
            self.logger.error(f"Failed to publish raw MQTT message: {e}")

    def get_subscription_info(self) -> Dict[str, Any]:
        """Get information about current subscriptions."""
        return {
            'subscribed_topics': list(self.topic_config.values()),
            'client_id': self.client_id,
            'broker': f"{self.host}:{self.port}"
        }