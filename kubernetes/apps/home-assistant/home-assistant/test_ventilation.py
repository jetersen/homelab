"""Exercise fan demand transitions in the matching Home Assistant Python runtime."""

import asyncio
import copy
import tempfile
import unittest
from pathlib import Path

import yaml
from homeassistant import loader
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.script import Script
from homeassistant.helpers.template import Template

PACKAGE = yaml.safe_load(Path(__file__).with_name("co2_ventilation.yaml").read_text())
FAN = "switch.utility_fan_plug"
HUMIDITY = "input_boolean.humidity_ventilation_demand"
CO2 = "input_boolean.co2_ventilation_demand"
TIMER = "timer.ventilation_fan_manual_run"
MODE = "input_select.ventilation_fan_mode"


class VentilationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.hass = HomeAssistant(self.directory.name)
        loader.async_setup(self.hass)
        self.commands = []
        self.dropped_commands = 0

        async def switch(service):
            self.commands.append(service.service)
            if self.dropped_commands:
                self.dropped_commands -= 1
                return
            self.hass.states.async_set(FAN, "on" if service.service == "turn_on" else "off")

        self.hass.services.async_register("switch", "turn_on", switch)
        self.hass.services.async_register("switch", "turn_off", switch)
        for entity, state in {
            FAN: "off",
            HUMIDITY: "off",
            CO2: "off",
            TIMER: "idle",
            MODE: "Auto",
        }.items():
            self.hass.states.async_set(entity, state)
        controller = next(a for a in PACKAGE["automation"] if a["id"] == "ventilation_fan_override")
        self.controller = Script(
            self.hass,
            cv.SCRIPT_SCHEMA(controller["actions"]),
            "Ventilation regression",
            "automation",
        )
        self.reason = Template(PACKAGE["template"][0]["sensor"][0]["state"], self.hass)
        retry = next(a for a in PACKAGE["automation"] if a["id"] == "ventilation_fan_retry")
        actions = copy.deepcopy(retry["actions"])
        # Exercise the retry loop without waiting a minute for each dropped command.
        actions[0]["repeat"]["sequence"][0]["delay"] = {"milliseconds": 10}
        self.retry = Script(
            self.hass,
            cv.SCRIPT_SCHEMA(actions),
            "Ventilation retry regression",
            "automation",
            script_mode=retry["mode"],
        )

        async def reconcile(service):
            self.assertEqual(service.data["entity_id"], ["automation.ventilation_fan_override"])
            await self.controller.async_run(context=Context())
            self.hass.states.async_set(
                "sensor.utility_fan_reason", self.reason.async_render().strip()
            )

        self.hass.services.async_register("automation", "trigger", reconcile)

    async def asyncTearDown(self):
        await self.hass.async_stop()
        self.directory.cleanup()

    async def change(self, entity, state, attributes=None):
        self.hass.states.async_set(entity, state, attributes)
        await self.controller.async_run({"trigger": {"id": "state"}}, context=Context())

    def assert_fan(self, state, reason):
        self.assertEqual(self.hass.states.get(FAN).state, state)
        self.assertEqual(self.reason.async_render().strip(), reason)

    async def test_cancel_manual_only_stops_without_creating_humidity_demand(self):
        await self.change(TIMER, "active")
        self.assert_fan("on", "Timed manual run")
        await self.change(TIMER, "idle", {"last_transition": "cancelled"})
        self.assert_fan("off", "Off")
        self.assertEqual(self.hass.states.get(HUMIDITY).state, "off")
        self.assertEqual(self.commands, ["turn_on", "turn_off"])

    async def test_expired_manual_only_run_stops(self):
        await self.change(TIMER, "active")
        await self.change(TIMER, "idle", {"last_transition": "finished"})
        self.assert_fan("off", "Off")

    async def test_cancel_preserves_existing_humidity_cycle_and_run_on(self):
        await self.change(HUMIDITY, "on")
        await self.change(TIMER, "active")
        self.assert_fan("on", "Timed manual run + Bathroom humidity / run-on")
        await self.change(TIMER, "idle", {"last_transition": "cancelled"})
        self.assert_fan("on", "Bathroom humidity / run-on")
        self.assertEqual(self.commands, ["turn_on"])
        await self.change(HUMIDITY, "off")
        self.assert_fan("off", "Off")

    async def test_humidity_can_start_during_manual_run_and_survive_expiry(self):
        await self.change(TIMER, "active")
        await self.change(HUMIDITY, "on")
        await self.change(TIMER, "idle", {"last_transition": "finished"})
        self.assert_fan("on", "Bathroom humidity / run-on")
        self.assertEqual(self.commands, ["turn_on"])

    async def test_humidity_finishing_does_not_interrupt_manual_run(self):
        await self.change(HUMIDITY, "on")
        await self.change(TIMER, "active")
        await self.change(HUMIDITY, "off")
        self.assert_fan("on", "Timed manual run")
        self.assertEqual(self.commands, ["turn_on"])

    async def test_cancel_preserves_co2_demand(self):
        await self.change(TIMER, "active")
        await self.change(CO2, "on")
        await self.change(TIMER, "idle", {"last_transition": "cancelled"})
        self.assert_fan("on", "CO2 ventilation")
        await self.change(CO2, "off")
        self.assert_fan("off", "Off")

    async def test_co2_finishing_does_not_interrupt_humidity_run_on(self):
        await self.change(HUMIDITY, "on")
        await self.change(CO2, "on")
        self.assert_fan("on", "CO2 ventilation + Bathroom humidity / run-on")
        await self.change(CO2, "off")
        self.assert_fan("on", "Bathroom humidity / run-on")
        self.assertEqual(self.commands, ["turn_on"])

    async def test_manual_modes_override_without_erasing_humidity_demand(self):
        await self.change(HUMIDITY, "on")
        await self.change(MODE, "Always off")
        self.assert_fan("off", "Off")
        self.assertEqual(self.hass.states.get(HUMIDITY).state, "on")
        await self.change(MODE, "Auto")
        self.assert_fan("on", "Bathroom humidity / run-on")
        await self.change(HUMIDITY, "off")
        await self.change(MODE, "Always on")
        await self.change(TIMER, "active")
        await self.change(TIMER, "idle")
        self.assert_fan("on", "Always on")

    async def test_switch_feedback_does_not_repeat_commands(self):
        await self.change(HUMIDITY, "on")
        await self.change(FAN, "on")
        self.assertEqual(self.commands, ["turn_on"])
        await self.change(FAN, "off")
        self.assert_fan("on", "Bathroom humidity / run-on")

    async def test_manual_modes_work_with_unavailable_humidity_demand(self):
        await self.change(HUMIDITY, "unavailable")
        await self.change(MODE, "Always on")
        self.assert_fan("on", "Always on")
        await self.change(MODE, "Always off")
        self.assert_fan("off", "Off")

    async def test_unknown_restored_demand_does_not_stop_running_fan(self):
        await self.change(TIMER, "active")
        await self.change(HUMIDITY, "unavailable")
        await self.change(TIMER, "idle")
        self.assert_fan("on", "On (reason unknown)")
        self.assertEqual(self.commands, ["turn_on"])
        await self.change(HUMIDITY, "off")
        self.assert_fan("off", "Off")

    async def test_retry_repeats_lost_shutoff_until_confirmed(self):
        self.hass.states.async_set(FAN, "on")
        self.hass.states.async_set("sensor.utility_fan_reason", "On (reason unknown)")
        self.dropped_commands = 2
        await asyncio.wait_for(self.retry.async_run(context=Context()), timeout=2)
        self.assert_fan("off", "Off")
        self.assertEqual(self.commands, ["turn_off"] * 3)

    async def test_retry_does_not_start_for_known_reasons(self):
        for reason in ["Off", "CO2 ventilation", "Timed manual run", "Always on", "unavailable"]:
            self.hass.states.async_set("sensor.utility_fan_reason", reason)
            await self.retry.async_run(context=Context())
        self.assertEqual(self.commands, [])

    async def test_reason_change_cancels_pending_retry(self):
        self.hass.states.async_set(FAN, "on")
        self.hass.states.async_set("sensor.utility_fan_reason", "On (reason unknown)")
        pending = asyncio.create_task(self.retry.async_run(context=Context()))
        await asyncio.sleep(0)
        self.hass.states.async_set(HUMIDITY, "on")
        self.hass.states.async_set("sensor.utility_fan_reason", "Bathroom humidity / run-on")
        # The state trigger restarts the script, cancelling its pending delay.
        await self.retry.async_run(context=Context())
        with self.assertRaises(asyncio.CancelledError):
            await pending
        self.assert_fan("on", "Bathroom humidity / run-on")
        self.assertEqual(self.commands, [])

    async def test_retry_keeps_unavailable_demand_guard(self):
        self.hass.states.async_set(FAN, "on")
        self.hass.states.async_set(HUMIDITY, "unavailable")
        self.hass.states.async_set("sensor.utility_fan_reason", "On (reason unknown)")
        with self.assertRaises(TimeoutError):
            await asyncio.wait_for(self.retry.async_run(context=Context()), timeout=0.05)
        self.assert_fan("on", "On (reason unknown)")
        self.assertEqual(self.commands, [])


if __name__ == "__main__":
    unittest.main()
