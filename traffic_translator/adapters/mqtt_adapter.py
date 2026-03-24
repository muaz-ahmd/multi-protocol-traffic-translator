"""
MQTT Adapter for Traffic Controllers

Enhanced MQTT client that serves as the central communication hub for the traffic translator.
Enforces a strict topic structure: traffic/{region}/{controller_id}/{message_type}/{phase_id}
"""

import logging
import asyncio
import json
import re
import time
from typing import Dict, Any, Optional, List, Callable

try:
    import paho.mqtt.client as mqtt
    PAHO_MQTT_AVAILABLE = True
except ImportError:
    PAHO_MQTT_AVAILABLE = False

from .base_adapter import BaseAdapter, EventDrivenAdapter
from ..config.models import AdapterModel
from ..core.message import TrafficMessage


class MQTTAdapter(EventDrivenAdapter):
    """
    MQTT adapter for traffic signal control.
    Enforces a strict topic structure for all traffic messages.
    """

    def __init__(self, name: str, config: AdapterModel):
        super().__init__(name, config)

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
        self.region = conn_params.get('region', 'default')
        self.topic_pattern = re.compile(r"^traffic/([^/]+)/([^/]+)/([^/]+)(?:/([^/]+))?$")
        
        # Standard subscriptions
        self.subscriptions = [
            f"traffic/{self.region}/+/status/#",
            f"traffic/{self.region}/+/feedback/#",
            f"traffic/{self.region}/+/error/#",
            f"traffic/{self.region}/+/command/#"
        ]

        # MQTT client
        self.client = None
        self._connected = False

        # Message queues (from BaseAdapter/EventDrivenAdapter)
        self._outgoing_queue = asyncio.Queue()
        self._incoming_queue = asyncio.Queue(maxsize=1000)

        # Statistics
        self._messages_sent = 0
        self._messages_received = 0
        self._error_count = 0

    async def connect(self) -> bool:
        """Establish MQTT connection."""
        if not PAHO_MQTT_AVAILABLE:
            self.logger.error("paho-mqtt not available.")
            return False

        try:
            self.logger.info(f"Connecting to MQTT broker at {self.host}:{self.port}")
            client = mqtt.Client(client_id=self.client_id, clean_session=True)
            self.client = client

            if self.username and self.password:
                client.username_pw_set(self.username, self.password)

            client.on_connect = self._on_connect
            client.on_disconnect = self._on_disconnect
            client.on_message = self._on_message

            client.connect(self.host, self.port, self.keepalive)
            client.loop_start()

            # Wait for connection
            timeout = 10
            start_time = time.time()
            while not client.is_connected() and (time.time() - start_time) < timeout:
                await asyncio.sleep(0.1)

            if not client.is_connected():
                self.logger.error("MQTT connection timeout")
                return False

            # Initial subscriptions
            for topic in self.subscriptions:
                client.subscribe(topic)

            self._connected = True
            self.logger.info(f"Successfully connected to MQTT broker as {self.client_id}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to connect: {e}")
            return False

    async def disconnect(self):
        """Disconnect from MQTT broker."""
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
        self._connected = False
        self.logger.info("Disconnected from MQTT broker")

    def _on_message(self, client, userdata, msg):
        """MQTT message callback."""
        topic = msg.topic
        match = self.topic_pattern.match(topic)
        
        if not match:
            self.logger.warning(f"Rejecting message with malformed topic: {topic}")
            return

        try:
            region, controller_id, message_type, phase_id = match.groups()
            payload = json.loads(msg.payload.decode())
            
            # Enrich payload from topic metadata
            payload['controller_id'] = controller_id
            payload['message_type'] = message_type
            if phase_id:
                payload['phase_id'] = phase_id

            message = TrafficMessage.from_mqtt(payload)
            
            # Post to incoming queue for the event loop
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.run_coroutine_threadsafe(self._incoming_queue.put(message), loop)
        except Exception as e:
            self.logger.error(f"Failed to process MQTT message on {topic}: {e}")
            self._error_count += 1

    async def _publish_message(self, message: TrafficMessage):
        """Publish TrafficMessage to MQTT using strict topic structure."""
        if not self.client or not self.client.is_connected():
            return

        topic = f"traffic/{self.region}/{message.controller_id}/{message.message_type}"
        if message.phase_id:
            topic += f"/{message.phase_id}"

        try:
            payload = json.dumps(message.to_dict())
            self.client.publish(topic, payload, qos=1)
        except Exception as e:
            self.logger.error(f"Failed to publish MQTT message: {e}")
            self._error_count += 1

    async def send_command(self, message: TrafficMessage) -> bool:
        """Route command to outgoing queue."""
        if not self._connected:
            return False
        await self._outgoing_queue.put(message)
        return True

    def is_connected(self) -> bool:
        """Check connection state."""
        return self._connected and self.client and self.client.is_connected()

    async def _event_loop(self):
        """Process incoming and outgoing queues."""
        self.logger.info("Starting MQTT event loop")
        try:
            while self._connected:
                # Process all pending incoming
                while not self._incoming_queue.empty():
                    message = await self._incoming_queue.get()
                    if self.message_callback:
                        self.message_callback(message)
                    self._messages_received += 1

                # Process all pending outgoing
                while not self._outgoing_queue.empty():
                    message = await self._outgoing_queue.get()
                    await self._publish_message(message)
                    self._messages_sent += 1

                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            self.logger.info("MQTT event loop cancelled")
        except Exception as e:
            self.logger.error(f"Error in MQTT event loop: {e}")

    def _on_connect(self, client, userdata, flags, rc):
        """Log connection and re-subscribe."""
        if rc == 0:
            self.logger.info("MQTT connected")
            for topic in self.subscriptions:
                client.subscribe(topic)
        else:
            self.logger.error(f"MQTT connection failed with code {rc}")

    def _on_disconnect(self, client, userdata, rc):
        """Handle disconnection."""
        self.logger.warning(f"MQTT disconnected with code {rc}")
        self._connected = False

    def get_subscription_info(self) -> Dict[str, Any]:
        """Return debugging info about subscriptions."""
        return {
            'region': self.region,
            'subscriptions': self.subscriptions,
            'messages_sent': self._messages_sent,
            'messages_received': self._messages_received
        }