"""Exercise headphone actions in an isolated, matching Home Assistant runtime."""

import tempfile
import unittest
from pathlib import Path

import yaml
from homeassistant import loader
from homeassistant.core import Context, HomeAssistant, SupportsResponse
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.script import Script

PACKAGE = yaml.safe_load(Path(__file__).with_name("music_headphones.yaml").read_text())
PHONE = "media_player.my_phone"
ROCKET = "media_player.rocket"
FRAMEWORK = "media_player.framework"
BLUETOOTH = "sensor.cph2709_bluetooth_connection"


class HeadphoneTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.hass = HomeAssistant(self.directory.name)
        loader.async_setup(self.hass)
        self.calls = []
        self.queues = {PHONE: 3, ROCKET: 3, FRAMEWORK: 3}

        async def queue(call):
            entity = call.data["entity_id"]
            if isinstance(entity, list):
                entity = entity[0]
            return {entity: {"items": self.queues[entity]}}

        async def record(call):
            self.calls.append((call.domain, call.service, dict(call.data)))

        self.hass.services.async_register(
            "music_assistant", "get_queue", queue, supports_response=SupportsResponse.ONLY
        )
        for domain, service in [
            ("music_assistant", "transfer_queue"),
            ("media_player", "media_play"),
            ("notify", "mobile_app_oneplus_nord_5"),
        ]:
            self.hass.services.async_register(domain, service, record)
        for entity in [PHONE, ROCKET, FRAMEWORK]:
            self.hass.states.async_set(entity, "paused")
        self.hass.states.async_set(
            BLUETOOTH, "1", {"connected_paired_devices": ["WH-1000XM6"]}
        )
        self.script = Script(
            self.hass,
            cv.SCRIPT_SCHEMA(PACKAGE["script"]["music_headphones_play"]["sequence"]),
            "Headphone regression",
            "script",
        )

    async def asyncTearDown(self):
        await self.hass.async_stop()
        self.directory.cleanup()

    async def run_action(self, operation):
        await self.script.async_run({"operation": operation}, context=Context())

    async def test_disconnected_headphones_never_play_or_transfer(self):
        self.hass.states.async_set(BLUETOOTH, "0", {"connected_paired_devices": []})
        await self.run_action("resume")
        await self.run_action("transfer")
        self.assertEqual(self.calls, [])

    async def test_resume_uses_phone_queue(self):
        await self.run_action("resume")
        self.assertEqual(self.calls[0][:2], ("media_player", "media_play"))
        self.assertEqual(self.calls[0][2]["entity_id"], [PHONE])

    async def test_empty_phone_queue_explains_transfer_without_starting_music(self):
        self.queues[PHONE] = 0
        await self.run_action("resume")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][0], "notify")
        self.assertIn("empty", self.calls[0][2]["message"])

    async def test_transfer_prefers_playing_desktop_over_paused_queue(self):
        self.hass.states.async_set(FRAMEWORK, "playing")
        await self.run_action("transfer")
        self.assertEqual(self.calls[0][:2], ("music_assistant", "transfer_queue"))
        self.assertEqual(self.calls[0][2]["source_player"], FRAMEWORK)
        self.assertEqual(self.calls[0][2]["entity_id"], [PHONE])
        self.assertTrue(self.calls[0][2]["auto_play"])

    async def test_empty_desktop_queues_do_not_replace_phone_queue(self):
        self.queues[ROCKET] = self.queues[FRAMEWORK] = 0
        await self.run_action("transfer")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][0], "notify")
        self.assertIn("Neither desktop", self.calls[0][2]["message"])

    async def test_unavailable_phone_explains_reconnection(self):
        self.hass.states.async_set(PHONE, "unavailable")
        await self.run_action("resume")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][0], "notify")
        self.assertIn("reconnect", self.calls[0][2]["message"])


if __name__ == "__main__":
    unittest.main()
