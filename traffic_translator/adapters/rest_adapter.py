"""
REST API Adapter for Traffic Controllers

Implements REST API integration for traffic controller communication.
"""

import logging
import asyncio
import json
from typing import Dict, Any, Optional, List

try:
    import aiohttp
    import requests
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

from .base_adapter import BaseAdapter, AdapterConfig, PollingAdapter
from ..core.message import TrafficMessage


class RESTAdapter(PollingAdapter):
    """
    REST API adapter for traffic controllers.

    Communicates with traffic controllers via RESTful HTTP APIs.
    """

    def __init__(self, config: AdapterConfig):
        super().__init__(config)

        # REST API configuration
        conn_params = config.connection_params or {}
        self.base_url = conn_params.get('base_url', 'http://localhost:8080')
        self.api_key = conn_params.get('api_key')
        self.username = conn_params.get('username')
        self.password = conn_params.get('password')
        self.timeout = conn_params.get('timeout', 10.0)

        # API endpoints
        self.endpoints = conn_params.get('endpoints', {
            'status': '/api/status',
            'command': '/api/command',
            'phases': '/api/phases',
            'detectors': '/api/detectors'
        })

        # HTTP session
        self.session = None

        # Authentication
        self.auth_headers = {}
        if self.api_key:
            self.auth_headers['Authorization'] = f'Bearer {self.api_key}'
        elif self.username and self.password:
            import base64
            auth_string = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
            self.auth_headers['Authorization'] = f'Basic {auth_string}'

        # Statistics
        self._messages_sent = 0
        self._messages_received = 0
        self._error_count = 0

    async def connect(self) -> bool:
        """
        Establish HTTP connection and test API.

        Returns:
            True if connection successful
        """
        if not AIOHTTP_AVAILABLE:
            self.logger.error("aiohttp not available. Install with: pip install aiohttp")
            return False

        try:
            self.logger.info(f"Connecting to REST API at {self.base_url}")

            # Create HTTP session
            self.session = aiohttp.ClientSession(
                headers=self.auth_headers,
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            )

            # Test connection with status endpoint
            test_url = f"{self.base_url}{self.endpoints.get('status', '/api/status')}"

            async with self.session.get(test_url) as response:
                if response.status not in [200, 201, 202]:
                    self.logger.error(f"API test failed with status {response.status}")
                    return False

                # Try to parse response
                try:
                    data = await response.json()
                    self.logger.debug(f"API test successful: {data}")
                except Exception:
                    # Some APIs might not return JSON
                    pass

            self._connected = True
            self.logger.info(f"Successfully connected to REST API {self.controller_id}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to connect to REST API: {e}")
            if self.session:
                await self.session.close()
                self.session = None
            return False

    async def disconnect(self):
        """Close HTTP session."""
        if self.session:
            await self.session.close()
            self.session = None
        self._connected = False
        self.logger.info(f"Disconnected from REST API {self.controller_id}")

    async def send_command(self, message: TrafficMessage) -> bool:
        """
        Send command via REST API POST.

        Args:
            message: Command message to send

        Returns:
            True if command sent successfully
        """
        if not self._validate_message_for_adapter(message):
            return False

        try:
            # Convert message to API payload
            payload = self._message_to_api_payload(message)

            # Send POST request
            command_url = f"{self.base_url}{self.endpoints.get('command', '/api/command')}"

            async with self.session.post(
                command_url,
                json=payload,
                headers={'Content-Type': 'application/json'}
            ) as response:

                if response.status not in [200, 201, 202, 204]:
                    error_text = await response.text()
                    self.logger.error(f"API command failed: {response.status} - {error_text}")
                    self._error_count += 1
                    return False

                self._messages_sent += 1
                self.logger.debug(f"Sent REST command: {message}")
                return True

        except Exception as e:
            self.logger.error(f"Failed to send REST command: {e}")
            self._error_count += 1
            return False

    async def request_status(self) -> Optional[TrafficMessage]:
        """
        Request current status via REST API GET.

        Returns:
            Status message or None if failed
        """
        try:
            # Request status
            status_url = f"{self.base_url}{self.endpoints.get('status', '/api/status')}"

            async with self.session.get(status_url) as response:
                if response.status != 200:
                    self.logger.error(f"Status request failed: {response.status}")
                    self._error_count += 1
                    return None

                data = await response.json()

                # Convert API response to TrafficMessage
                message = self._api_response_to_message(data)

                self._messages_received += 1
                return message

        except Exception as e:
            self.logger.error(f"Failed to request REST status: {e}")
            self._error_count += 1
            return None

    def is_connected(self) -> bool:
        """Check HTTP session status."""
        return self._connected and self.session and not self.session.closed

    def _message_to_api_payload(self, message: TrafficMessage) -> Dict[str, Any]:
        """Convert TrafficMessage to API payload."""
        payload = {
            'controller_id': message.controller_id,
            'timestamp': message.timestamp,
            'message_type': message.message_type
        }

        if message.message_type == 'command':
            payload.update({
                'phase_id': message.phase_id,
                'command': message.command,
                'duration': message.duration,
                'priority': message.priority
            })

        return payload

    def _api_response_to_message(self, response_data: Dict[str, Any]) -> TrafficMessage:
        """Convert API response to TrafficMessage."""
        message_type = response_data.get('message_type', 'status')
        controller_id = response_data.get('controller_id', self.controller_id)

        if message_type == 'status':
            return TrafficMessage.create_status(
                controller_id=controller_id,
                current_phase=response_data.get('current_phase'),
                phase_status=response_data.get('phase_status', {})
            )

        elif message_type == 'feedback':
            return TrafficMessage.create_feedback(
                controller_id=controller_id,
                phase_id=response_data.get('phase_id'),
                detector_status=response_data.get('detector_status', {})
            )

        else:
            # Generic message
            return TrafficMessage(
                timestamp=response_data.get('timestamp', asyncio.get_event_loop().time()),
                controller_id=controller_id,
                message_type=message_type,
                protocol_data=response_data
            )

    async def get_phases(self) -> Optional[Dict[str, Any]]:
        """Get phase configuration from API."""
        try:
            phases_url = f"{self.base_url}{self.endpoints.get('phases', '/api/phases')}"

            async with self.session.get(phases_url) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    self.logger.warning(f"Failed to get phases: {response.status}")
                    return None

        except Exception as e:
            self.logger.error(f"Error getting phases: {e}")
            return None

    async def get_detectors(self) -> Optional[Dict[str, Any]]:
        """Get detector configuration from API."""
        try:
            detectors_url = f"{self.base_url}{self.endpoints.get('detectors', '/api/detectors')}"

            async with self.session.get(detectors_url) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    self.logger.warning(f"Failed to get detectors: {response.status}")
                    return None

        except Exception as e:
            self.logger.error(f"Error getting detectors: {e}")
            return None

    async def send_batch_commands(self, messages: List[TrafficMessage]) -> List[bool]:
        """
        Send multiple commands in batch.

        Args:
            messages: List of command messages

        Returns:
            List of success flags
        """
        results = []

        # Send commands sequentially (could be optimized with concurrent requests)
        for message in messages:
            success = await self.send_command(message)
            results.append(success)

            # Small delay between commands
            await asyncio.sleep(0.1)

        return results