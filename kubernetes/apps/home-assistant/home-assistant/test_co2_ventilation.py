"""Exercise ventilation decisions using the deployed YAML templates."""

import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import yaml
from jinja2.nativetypes import NativeEnvironment

PACKAGE = yaml.safe_load(Path(__file__).with_name("co2_ventilation.yaml").read_text())
NOW = datetime(2026, 10, 12, 12, tzinfo=UTC)


class States:
    def __init__(self, values, invalid_minutes):
        self.values = values
        self.binary_sensor = SimpleNamespace(
            co2_ventilation_high=SimpleNamespace(
                last_changed=NOW - timedelta(minutes=invalid_minutes)
            )
        )

    def __call__(self, entity_id):
        return str(self.values.get(entity_id, "unknown"))


def timestamp(value, default=0):
    try:
        return (
            value.timestamp()
            if isinstance(value, datetime)
            else datetime.fromisoformat(value).timestamp()
        )
    except (ValueError, TypeError):
        return default


class VentilationTest(unittest.TestCase):
    def setUp(self):
        self.values = {
            "sensor.apollo_air_1_2c778c_co2": "1200",
            "binary_sensor.co2_ventilation_high": "on",
            "binary_sensor.co2_ventilation_low": "off",
            "input_boolean.co2_ventilation_demand": "off",
            "input_select.ventilation_fan_mode": "Auto",
            "input_datetime.co2_ventilation_deadline": (NOW + timedelta(minutes=30)).isoformat(),
            "input_datetime.co2_ventilation_next_allowed": (NOW - timedelta(minutes=1)).isoformat(),
        }
        self.environment = NativeEnvironment()

    def render(self, template, context):
        return self.environment.from_string(template).render(context)

    def decision(self, automation_index=0, invalid_minutes=0):
        states = States(self.values, invalid_minutes)
        context = {
            "states": states,
            "is_state": lambda entity, value: states(entity) == value,
            "is_number": lambda value: (
                value not in ("unknown", "unavailable") and float(value) == float(value)
            ),
            "as_timestamp": timestamp,
            "state_attr": lambda entity, attribute: (
                timestamp(states(entity)) if attribute == "timestamp" else None
            ),
            "now": lambda: NOW,
        }
        automation = PACKAGE["automation"][automation_index]
        for action in automation["actions"]:
            for key, value in action.get("variables", {}).items():
                context[key] = self.render(value, context)

        def matches(condition):
            kind = condition["condition"]
            if kind == "state":
                return states(condition["entity_id"]) == condition["state"]
            if kind == "template":
                return bool(self.render(condition["value_template"], context))
            nested = [matches(child) for child in condition["conditions"]]
            return all(nested) if kind == "and" else any(nested)

        choices = automation["actions"][-1]["choose"]
        return next(
            (
                index
                for index, choice in enumerate(choices)
                if all(matches(condition) for condition in choice["conditions"])
            ),
            None,
        )

    def test_sustained_high_starts_demand(self):
        self.assertEqual(self.decision(), 1)
        self.values["binary_sensor.co2_ventilation_high"] = "off"
        self.assertIsNone(self.decision())

    def test_deadline_survives_a_restart_or_missed_time_trigger(self):
        self.values["input_boolean.co2_ventilation_demand"] = "on"
        self.values["input_datetime.co2_ventilation_deadline"] = (
            NOW - timedelta(minutes=1)
        ).isoformat()
        self.assertEqual(self.decision(), 0)

    def test_low_threshold_has_hysteresis(self):
        self.values["input_boolean.co2_ventilation_demand"] = "on"
        self.values["sensor.apollo_air_1_2c778c_co2"] = "900"
        self.values["binary_sensor.co2_ventilation_high"] = "off"
        self.assertIsNone(self.decision())
        self.values["binary_sensor.co2_ventilation_low"] = "on"
        self.assertEqual(self.decision(), 0)

    def test_sensor_loss_has_a_grace_period(self):
        self.values["input_boolean.co2_ventilation_demand"] = "on"
        self.values["sensor.apollo_air_1_2c778c_co2"] = "unavailable"
        self.values["binary_sensor.co2_ventilation_high"] = "unavailable"
        self.assertIsNone(self.decision(invalid_minutes=4))
        self.assertEqual(self.decision(invalid_minutes=5), 0)

    def test_invalid_readings_never_start_demand(self):
        for value in ["unknown", "unavailable", "0", "-1"]:
            with self.subTest(value=value):
                self.values["sensor.apollo_air_1_2c778c_co2"] = value
                self.assertIsNone(self.decision(invalid_minutes=10))

    def test_timeout_cooldown_prevents_restarting_while_still_high(self):
        self.values["input_datetime.co2_ventilation_next_allowed"] = (
            NOW + timedelta(minutes=30)
        ).isoformat()
        self.assertIsNone(self.decision())

    def test_deadlines_use_absolute_timestamps_in_copenhagen(self):
        self.values["input_boolean.co2_ventilation_demand"] = "on"
        self.values["input_datetime.co2_ventilation_deadline"] = "2026-10-12T13:59:00+02:00"
        self.assertEqual(self.decision(), 0)

    def test_manual_modes_release_and_prevent_co2_demand(self):
        for mode in ["Always on", "Always off"]:
            with self.subTest(mode=mode):
                self.values["input_select.ventilation_fan_mode"] = mode
                self.assertIsNone(self.decision())
                self.values["input_boolean.co2_ventilation_demand"] = "on"
                self.assertEqual(self.decision(), 0)
                self.values["input_boolean.co2_ventilation_demand"] = "off"

    def test_always_off_wins_over_co2_demand(self):
        self.values["input_boolean.co2_ventilation_demand"] = "on"
        self.values["input_select.ventilation_fan_mode"] = "Always off"
        self.assertEqual(self.decision(1), 0)

    def test_manual_on_and_auto_handoff(self):
        self.values["input_select.ventilation_fan_mode"] = "Always on"
        self.assertEqual(self.decision(1), 1)
        self.values["input_select.ventilation_fan_mode"] = "Auto"
        self.assertEqual(self.decision(1), 2)
        self.values["input_boolean.co2_ventilation_demand"] = "on"
        self.assertEqual(self.decision(1), 1)


if __name__ == "__main__":
    unittest.main()
