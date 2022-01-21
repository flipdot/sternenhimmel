import json
import logging
import os
from time import sleep
import math

import paho.mqtt.client as mqtt
import sentry_sdk

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

sentry_sdk.init(
    os.environ.get("SENTRY_DSN"),
    ignore_errors=[KeyboardInterrupt],

    # Set traces_sample_rate to 1.0 to capture 100%
    # of transactions for performance monitoring.
    # We recommend adjusting this value in production.
    traces_sample_rate=0,
)

MAX_BRIGHTNESS = 255
DEFAULT_BRIGHTNESS = 0.4
BRIGHTNESS_STEP_SIZE = 0.3
DEFAULT_FREQUENCY = 0.5
FREQUENCY_STEP_SIZE = 0.2


def update_state_recursive(obj, key, value):
    if "/" in key:
        a, _, b = key.partition("/")
        if a not in obj:
            obj[a] = {}
        update_state_recursive(obj[a], b, value)
    else:
        obj[key] = value


class Sternenhimmel:

    def __init__(self):
        def on_connect(client, userdata, flags, rc):
            logger.info(f"Connected with result code {rc}")
            client.subscribe("zigbee2mqtt/switch/#")
            client.subscribe("zigbee2mqtt/bridge/devices")
            client.subscribe("sternenhimmel/#")

        def on_message(client, userdata, msg):
            logger.info(f"Received on {msg.topic}: {msg.payload}")
            try:
                data = json.loads(msg.payload)
            except json.JSONDecodeError:
                self.mqtt.publish("sternenhimmel/error", json.dumps({"error": f"received invalid json on topic {msg.topic}"}))
                return
            if msg.topic == "zigbee2mqtt/bridge/devices":
                self.on_lights_message(data)
            elif msg.topic.startswith("zigbee2mqtt/switch/"):
                switch = msg.topic.rpartition("/")[2]
                if "brightness" in msg.topic:
                    self.on_brightness_switch_action(switch, data)
                elif "frequency" in msg.topic:
                    self.on_frequency_switch_action(switch, data)
                else:
                    self.on_switch_action(switch, data)
            elif msg.topic.startswith("sternenhimmel/"):
                key = msg.topic.partition("/")[2]
                self.on_sternenhimmel_state(key, data)
                self.update()

        self.lights = []
        self.light_groups = {}
        self.state = {}
        self.mqtt = mqtt.Client()
        self.mqtt.on_connect = on_connect
        self.mqtt.on_message = on_message
        self.step = 0

    def on_lights_message(self, data):
        self.lights = [x["friendly_name"].partition("/")[2] for x in data if
                       x["friendly_name"].startswith("light/")]
        groups = set([l[0] for l in self.lights])
        self.light_groups = {
            g: [l for l in self.lights if l.startswith(g)]
            for g in groups
        }

    def on_sternenhimmel_state(self, key, data):
        update_state_recursive(self.state, key, data)
        logger.info(f"State: {self.state}")

    def on_switch_action(self, switch, data):
        # Take every character of the switch name as a group name
        groups = set(switch)
        for group in groups:
            payload = {}
            if data.get("action") == "on":
                payload["on"] = True
            elif data.get("action") == "off":
                payload["on"] = False

            payload["increase_brightness"] = data.get("action") == "brightness_move_up"
            payload["decrease_brightness"] = data.get("action") == "brightness_move_down"

            self.update_sternenhimmel_state(group, payload)
            self.update()

    def on_brightness_switch_action(self, switch, data):
        # Take every character of the switch name as a group name
        groups = set(switch)
        for group in groups:
            group_state = self.state.get("group", {}).get(group, {})
            payload = {
                "on": True,
                "amplitude": group_state.get("amplitude", DEFAULT_BRIGHTNESS)
            }
            if data.get("action") == "on":
                payload["amplitude"] += BRIGHTNESS_STEP_SIZE
            elif data.get("action") == "off":
                payload["amplitude"] -= BRIGHTNESS_STEP_SIZE
            elif data.get("action") == "brightness_move_up":  # long press up
                payload["frequency"] = 0
                payload["amplitude"] = 1
            elif data.get("action") == "brightness_move_down":  # long press down
                payload["frequency"] = DEFAULT_FREQUENCY
                payload["amplitude"] = min(payload["amplitude"], DEFAULT_BRIGHTNESS)

            # Keep only one digit after the decimal point
            payload["amplitude"] = round(payload["amplitude"], 1)
            # clamp between 0 and 1
            payload["amplitude"] = max(0, min(1, payload["amplitude"]))

            self.update_sternenhimmel_state(group, payload)
            self.update()

    def on_frequency_switch_action(self, switch, data):
        # Take every character of the switch name as a group name
        groups = set(switch)
        for group in groups:
            group_state = self.state.get("group", {}).get(group, {})
            if not group_state.get("on"):
                # don't change settings of lights that are turned off
                continue
            payload = {
                "frequency": group_state.get("frequency", DEFAULT_FREQUENCY)
            }
            if data.get("action") == "on":
                payload["frequency"] += FREQUENCY_STEP_SIZE
            elif data.get("action") == "off":
                payload["frequency"] -= FREQUENCY_STEP_SIZE
            elif data.get("action") == "brightness_move_up":  # long press up
                payload["frequency"] = 2.4  # Party mode!
            elif data.get("action") == "brightness_move_down":  # long press down
                payload["frequency"] = 0

            # Keep only one digit after the decimal point
            payload["frequency"] = round(payload["frequency"], 1)

            self.update_sternenhimmel_state(group, payload)
            self.update()

    def update_sternenhimmel_state(self, group, update: dict):
        payload = self.state["group"].get(group, {})
        payload.update(update)
        self.mqtt.publish(f"sternenhimmel/group/{group}", json.dumps(payload), retain=True)

    def set_light(self, light_name, brightness_percent, transition=0, force_on=False):
        if brightness_percent < 0 or brightness_percent > 1:
            raise ValueError(f"Brightness must be between 0 and 1, was {brightness_percent}")
        logger.debug(f"Brightness for {light_name}={brightness_percent}")
        brightness = round(brightness_percent * MAX_BRIGHTNESS, 2)
        if force_on and brightness < 1:
            brightness = 1
        self.mqtt.publish(f"zigbee2mqtt/light/{light_name}/set", json.dumps({
            "state": "ON",
            "brightness": brightness,
            "transition": transition,
        }))

    def run_forever(self):
        self.mqtt.connect("localhost", 1883, 60)
        self.mqtt.loop_start()
        while True:
            self.update()
            self.step += 1
            sleep(1)

    def update(self):
        if not self.state:
            return
        for group, lights in self.light_groups.items():
            for i, light in enumerate(lights):
                group_state = self.state.get("group", {}).get(group, {})
                if not group_state.get("on"):
                    self.set_light(light, 0, transition=0)
                    continue
                offset = (2 * math.pi) * i / len(lights)
                amplitude = group_state.get("amplitude", DEFAULT_BRIGHTNESS)
                # if group_state.get("increase_brightness") and amplitude < 1:
                #     amplitude += BRIGHTNESS_STEP_SIZE
                # if group_state.get("decrease_brightness") and amplitude:
                #     amplitude -= BRIGHTNESS_STEP_SIZE
                # clamp value to be between 0 and 1
                amplitude = min(1, max(0, amplitude))
                # if amplitude != group_state.get("amplitude"):
                #     self.update_sternenhimmel_state(group, {"amplitude": amplitude})
                frequency = group_state.get("frequency", DEFAULT_FREQUENCY)
                if not frequency:
                    brightness = amplitude
                else:
                    brightness = (math.sin(self.step * frequency + offset) + 1) / 2 * amplitude
                self.set_light(light, brightness, transition=1, force_on=True)


if __name__ == '__main__':
    sternenhimmel = Sternenhimmel()
    sternenhimmel.run_forever()
