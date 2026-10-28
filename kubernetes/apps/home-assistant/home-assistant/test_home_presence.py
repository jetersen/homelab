"""Exercise presence updates in an isolated, matching Home Assistant runtime."""

import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

import yaml
from homeassistant import loader
from homeassistant.config_entries import ConfigEntries
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import trigger
from homeassistant.setup import async_setup_component

PACKAGE = yaml.safe_load(Path(__file__).with_name("home_presence.yaml").read_text())
PERSON = "person.joseph_petersen"
WIFI = "sensor.cph2709_wi_fi_connection"
HOME = "input_boolean.at_home"
HOME_WIFI = "The Creep Nextdoor 5G"


class PresenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.hass = HomeAssistant(self.directory.name)
        loader.async_setup(self.hass)
        self.hass.config_entries = ConfigEntries(self.hass, {})
        await self.hass.config_entries.async_initialize()
        dr.async_setup(self.hass)
        await dr.async_load(self.hass)
        await er.async_load(self.hass)
        await trigger.async_setup(self.hass)
        self.calls = []

        async def update(call):
            self.calls.append(call.service)
            self.hass.states.async_set(HOME, "on" if call.service == "turn_on" else "off")

        for service in ["turn_on", "turn_off"]:
            self.hass.services.async_register("input_boolean", service, update)

    async def asyncTearDown(self):
        await self.hass.async_stop()
        self.directory.cleanup()

    async def start_presence(self, person, wifi, restored="off"):
        self.hass.states.async_set(PERSON, person)
        self.hass.states.async_set(WIFI, wifi)
        self.hass.states.async_set(HOME, restored)
        automation = deepcopy(PACKAGE["automation"])
        self.assertTrue(
            await async_setup_component(self.hass, "timer", {"timer": PACKAGE["timer"]})
        )
        self.assertTrue(
            await async_setup_component(self.hass, "automation", {"automation": automation})
        )
        await self.hass.async_start()
        await self.hass.async_block_till_done()

    def assert_home(self, expected):
        self.assertEqual(self.hass.states.get(HOME).state, expected)

    async def settle_departure(self):
        if self.hass.states.is_state("timer.home_presence_departure", "active"):
            self.assertEqual(
                self.hass.states.get("timer.home_presence_departure").attributes["duration"],
                "0:15:00",
            )
            await self.hass.services.async_call(
                "timer", "finish", {"entity_id": "timer.home_presence_departure"}, blocking=True
            )
        await self.hass.async_block_till_done()

    async def test_startup_reconciles_person_home(self):
        await self.start_presence("home", "unknown")
        self.assert_home("on")

    async def test_startup_reconciles_home_wifi_without_gps(self):
        await self.start_presence("unavailable", HOME_WIFI)
        self.assert_home("on")

    async def test_startup_unknown_preserves_restored_home(self):
        await self.start_presence("unknown", "unavailable", restored="on")
        await self.settle_departure()
        self.assert_home("on")
        self.assertEqual(self.calls, [])

    async def test_startup_away_waits_before_clearing_restored_home(self):
        await self.start_presence("not_home", "Other Wi-Fi", restored="on")
        self.assert_home("on")
        await self.settle_departure()
        self.assert_home("off")

    async def test_departure_requires_both_signals_to_remain_away(self):
        await self.start_presence("home", HOME_WIFI)
        self.hass.states.async_set(PERSON, "not_home")
        await self.settle_departure()
        self.assert_home("on")
        self.hass.states.async_set(WIFI, "Other Wi-Fi")
        await self.hass.async_block_till_done()
        self.assert_home("on")
        await self.settle_departure()
        self.assert_home("off")

    async def test_arrival_cancels_pending_departure(self):
        await self.start_presence("not_home", "Other Wi-Fi", restored="on")
        self.hass.states.async_set(WIFI, HOME_WIFI)
        await self.hass.async_block_till_done()
        await self.settle_departure()
        self.assert_home("on")
        self.assertNotIn("turn_off", self.calls)

    async def test_lost_presence_cancels_pending_departure(self):
        await self.start_presence("not_home", "Other Wi-Fi", restored="on")
        self.hass.states.async_set(PERSON, "unavailable")
        await self.hass.async_block_till_done()
        await self.settle_departure()
        self.assert_home("on")
        self.assertNotIn("turn_off", self.calls)

    async def test_either_home_signal_turns_helper_on(self):
        await self.start_presence("unknown", "unknown")
        self.hass.states.async_set(WIFI, HOME_WIFI)
        await self.hass.async_block_till_done()
        self.assert_home("on")
        self.hass.states.async_set(HOME, "off")
        self.hass.states.async_set(PERSON, "home")
        await self.hass.async_block_till_done()
        self.assert_home("on")

    async def test_reload_reconciles_home_after_manual_toggle(self):
        await self.start_presence("home", HOME_WIFI)
        self.hass.states.async_set(HOME, "off")
        self.hass.bus.async_fire("automation_reloaded")
        await self.hass.async_block_till_done()
        self.assert_home("on")

    async def test_away_zone_changes_preserve_the_running_timer(self):
        await self.start_presence("not_home", "Other Wi-Fi", restored="on")
        before = self.hass.states.get("timer.home_presence_departure").attributes["finishes_at"]
        self.hass.states.async_set(PERSON, "work")
        await self.hass.async_block_till_done()
        after = self.hass.states.get("timer.home_presence_departure").attributes["finishes_at"]
        self.assertEqual(before, after)
        self.assert_home("on")

    async def test_stale_expiry_does_not_bypass_a_running_timer(self):
        await self.start_presence("not_home", "Other Wi-Fi", restored="on")
        self.hass.bus.async_fire("timer.finished", {"entity_id": "timer.home_presence_departure"})
        await self.hass.async_block_till_done()
        self.assert_home("on")


if __name__ == "__main__":
    unittest.main()
