"""Exercise headphone actions in an isolated, matching Home Assistant runtime."""

import asyncio
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

import yaml
from homeassistant import loader
from homeassistant.config_entries import ConfigEntries
from homeassistant.core import Context, HomeAssistant, State, SupportsResponse
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.script import Script
from homeassistant.helpers.template import Template
from homeassistant.setup import async_setup_component

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
        self.launches = []
        self.queue_hook = None
        self.queues = {PHONE: 3, ROCKET: 3, FRAMEWORK: 3}

        async def queue(call):
            entity = call.data["entity_id"]
            if isinstance(entity, list):
                entity = entity[0]
            if self.queue_hook:
                self.queue_hook()
            return {entity: {"items": self.queues[entity]}}

        async def record(call):
            if call.data.get("message") == "command_activity":
                self.launches.append(dict(call.data))
            else:
                self.calls.append((call.domain, call.service, dict(call.data)))

        self.hass.services.async_register(
            "music_assistant", "get_queue", queue, supports_response=SupportsResponse.ONLY
        )
        for domain, service in [
            ("music_assistant", "transfer_queue"),
            ("media_player", "media_play"),
            ("notify", "mobile_app_oneplus_nord_5"),
            ("script", "music_headphones_prompt"),
        ]:
            self.hass.services.async_register(domain, service, record)
        for entity in [PHONE, ROCKET, FRAMEWORK]:
            self.hass.states.async_set(entity, "paused")
        self.hass.states.async_set(BLUETOOTH, "1", {"connected_paired_devices": ["WH-1000XM6"]})
        sequence = deepcopy(PACKAGE["script"]["music_headphones_play"]["sequence"])
        next(step for step in sequence if "wait_template" in step)["timeout"] = 0.1
        self.script = Script(
            self.hass,
            cv.SCRIPT_SCHEMA(sequence),
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
        await self.run_action("handoff")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.launches, [])

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

    async def test_handoff_launches_app_and_transfers_playing_rocket(self):
        self.hass.states.async_set(ROCKET, "playing")
        await self.run_action("handoff")
        self.assertEqual(
            self.launches[0]["data"]["intent_package_name"], "io.music_assistant.client"
        )
        self.assertEqual(self.calls[0][2]["source_player"], ROCKET)
        self.assertTrue(self.calls[0][2]["auto_play"])

    async def test_handoff_prefers_playing_framework(self):
        self.hass.states.async_set(FRAMEWORK, "playing")
        await self.run_action("handoff")
        self.assertEqual(self.calls[0][2]["source_player"], FRAMEWORK)

    async def test_handoff_leaves_paused_queues_alone(self):
        await self.run_action("handoff")
        self.assertEqual([call[:2] for call in self.calls], [("script", "music_headphones_prompt")])

    async def test_handoff_waits_for_phone_to_reconnect(self):
        self.hass.states.async_set(PHONE, "unavailable")
        self.hass.states.async_set(ROCKET, "playing")
        task = asyncio.create_task(self.run_action("handoff"))
        await asyncio.sleep(0.01)
        self.assertEqual(self.calls, [])
        self.assertEqual(len(self.launches), 1)
        self.hass.states.async_set(PHONE, "idle")
        await task
        self.assertEqual(self.calls[0][2]["source_player"], ROCKET)

    async def test_disconnect_during_startup_prevents_transfer(self):
        self.hass.states.async_set(PHONE, "unavailable")
        self.hass.states.async_set(ROCKET, "playing")
        task = asyncio.create_task(self.run_action("handoff"))
        await asyncio.sleep(0.01)
        self.hass.states.async_set(BLUETOOTH, "0", {"connected_paired_devices": []})
        self.hass.states.async_set(PHONE, "idle")
        await task
        self.assertEqual(self.calls, [])

    def prepare_return(self):
        for entity, state in {
            "input_boolean.at_home": "on",
            "binary_sensor.rocket_sensor_power": "on",
            "binary_sensor.music_headphones_playback": "on",
            PHONE: "playing",
        }.items():
            self.hass.states.async_set(entity, state)
        self.hass.states.async_set(BLUETOOTH, "0", {"connected_paired_devices": []})
        return Script(
            self.hass,
            cv.SCRIPT_SCHEMA(PACKAGE["script"]["music_headphones_return"]["sequence"]),
            "Return regression",
            "script",
        )

    async def test_return_moves_phone_queue_to_powered_rocket(self):
        script = self.prepare_return()
        await script.async_run(context=Context())
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][:2], ("music_assistant", "transfer_queue"))
        self.assertEqual(self.calls[0][2]["source_player"], PHONE)
        self.assertEqual(self.calls[0][2]["entity_id"], [ROCKET])
        self.assertTrue(self.calls[0][2]["auto_play"])

    async def test_return_handles_android_pause_on_disconnect(self):
        script = self.prepare_return()
        self.hass.states.async_set(PHONE, "paused")
        await script.async_run(context=Context())
        self.assertEqual(self.calls[0][2]["source_player"], PHONE)

    async def test_return_requires_home_power_recent_playback_and_available_players(self):
        for entity, state in [
            ("input_boolean.at_home", "off"),
            ("input_boolean.at_home", "unknown"),
            ("binary_sensor.rocket_sensor_power", "off"),
            ("binary_sensor.rocket_sensor_power", "unavailable"),
            ("binary_sensor.music_headphones_playback", "off"),
            (PHONE, "unavailable"),
            (PHONE, "idle"),
            (ROCKET, "unavailable"),
            (ROCKET, "off"),
            (BLUETOOTH, "unavailable"),
            (BLUETOOTH, "unknown"),
        ]:
            with self.subTest(entity=entity, state=state):
                script = self.prepare_return()
                self.hass.states.async_set(ROCKET, "paused")
                self.hass.states.async_set(entity, state)
                await script.async_run(context=Context())
                self.assertEqual(self.calls, [])

    async def test_return_requires_confirmed_headphone_disconnection(self):
        for attributes in [{}, {"connected_paired_devices": ["WH-1000XM6"]}]:
            script = self.prepare_return()
            self.hass.states.async_set(BLUETOOTH, "1", attributes)
            await script.async_run(context=Context())
            self.assertEqual(self.calls, [])

    async def test_return_does_not_transfer_empty_queue(self):
        script = self.prepare_return()
        self.queues[PHONE] = 0
        await script.async_run(context=Context())
        self.assertEqual(self.calls, [])

    async def test_return_rechecks_headphones_after_fetching_queue(self):
        script = self.prepare_return()
        self.queue_hook = lambda: self.hass.states.async_set(
            BLUETOOTH, "1", {"connected_paired_devices": ["WH-1000XM6"]}
        )
        await script.async_run(context=Context())
        self.assertEqual(self.calls, [])

    async def test_disconnect_trigger_requires_a_real_headphone_removal(self):
        automation = next(
            a for a in PACKAGE["automation"] if a["id"] == "music_headphones_disconnected"
        )
        template = Template(automation["conditions"][0]["value_template"], self.hass)
        connected = State(BLUETOOTH, "1", {"connected_paired_devices": ["WH-1000XM6"]})
        disconnected = State(BLUETOOTH, "0", {"connected_paired_devices": []})
        for before, after, expected in [
            (connected, disconnected, True),
            (None, disconnected, False),
            (connected, State(BLUETOOTH, "unavailable"), False),
            (connected, State(BLUETOOTH, "0"), False),
            (State(BLUETOOTH, "unavailable", connected.attributes), disconnected, False),
            (disconnected, disconnected, False),
            (disconnected, connected, False),
        ]:
            with self.subTest(before=before, after=after):
                self.assertEqual(
                    template.async_render({"trigger": {"from_state": before, "to_state": after}}),
                    expected,
                )

    async def test_playback_sensor_retains_brief_pause_then_expires(self):
        self.hass.states.async_set(PHONE, "playing")
        config = deepcopy(PACKAGE["template"])
        config[0]["binary_sensor"][0]["delay_off"] = 0.05
        self.hass.config_entries = ConfigEntries(self.hass, {})
        await self.hass.config_entries.async_initialize()
        dr.async_setup(self.hass)
        await dr.async_load(self.hass)
        await er.async_load(self.hass)
        self.assertTrue(await async_setup_component(self.hass, "template", {"template": config}))
        await self.hass.async_start()
        await self.hass.async_block_till_done()
        sensor = "binary_sensor.music_headphones_playback"
        self.assertEqual(self.hass.states.get(sensor).state, "on")
        self.hass.states.async_set(PHONE, "paused")
        self.hass.states.async_set(BLUETOOTH, "0", {"connected_paired_devices": []})
        await self.hass.async_block_till_done()
        self.assertEqual(self.hass.states.get(sensor).state, "on")
        await asyncio.sleep(0.1)
        await self.hass.async_block_till_done()
        self.assertEqual(self.hass.states.get(sensor).state, "off")

    async def test_unavailable_phone_explains_reconnection(self):
        self.hass.states.async_set(PHONE, "unavailable")
        await self.run_action("resume")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][0], "notify")
        self.assertIn("reconnect", self.calls[0][2]["message"])


if __name__ == "__main__":
    unittest.main()
