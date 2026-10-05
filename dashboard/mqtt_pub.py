"""Optional MQTT publisher of the /api/health JSON (every 5 s).

DISABLED by default. When AGX_MQTT_ENABLED != 1 or AGX_MQTT_HOST is empty, start_mqtt() returns
None and nothing is imported or opened (no socket). Credentials are never logged.
Topic: <AGX_MQTT_TOPIC_PREFIX>/agx02/health (prefix optional).
"""
from __future__ import annotations

import json
import logging
import ssl
import threading
from typing import Callable

from common.env import get, truthy

log = logging.getLogger("dashboard.mqtt")


class MqttPublisher:
    def __init__(self, env: dict, health_fn: Callable[[], dict], interval_s: float = 5.0,
                 node: str = "agx02"):
        import paho.mqtt.client as mqtt  # imported only when enabled

        self._mqtt = mqtt
        self.host = get(env, "AGX_MQTT_HOST")
        port_s = get(env, "AGX_MQTT_PORT")
        self.tls = truthy(get(env, "AGX_MQTT_TLS"))
        self.port = int(port_s) if port_s.isdigit() else (8883 if self.tls else 1883)
        prefix = get(env, "AGX_MQTT_TOPIC_PREFIX").strip("/")
        self.topic = f"{prefix}/{node}/health" if prefix else f"{node}/health"
        self.health_fn = health_fn
        self.interval = float(interval_s)
        self._stop = threading.Event()
        # paho-mqtt 2.x needs the callback API version as first argument; 1.x does not have it.
        if hasattr(mqtt, "CallbackAPIVersion"):
            self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"{node}-dashboard")
        else:
            self.client = mqtt.Client(client_id=f"{node}-dashboard")
        user = get(env, "AGX_MQTT_USER")
        if user:
            if not self.tls:
                # the user name and password go to the broker in clear text without TLS
                log.warning("mqtt: AGX_MQTT_USER is set but AGX_MQTT_TLS is not 1: the MQTT "
                            "credentials are sent without encryption. Set AGX_MQTT_TLS=1 or use "
                            "a broker that is reachable only on a trusted network (tailscale).")
            self.client.username_pw_set(user, get(env, "AGX_MQTT_PASSWORD") or None)
        if self.tls:
            self.client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
        self.client.reconnect_delay_set(min_delay=1, max_delay=60)

    def start(self):
        log.info("mqtt enabled: host %s port %d topic %s tls %s", self.host, self.port, self.topic, self.tls)
        self.client.connect_async(self.host, self.port, keepalive=30)
        self.client.loop_start()
        threading.Thread(target=self._loop, name="mqtt-pub", daemon=True).start()

    def _loop(self):
        while not self._stop.wait(self.interval):
            try:
                if self.client.is_connected():
                    payload = json.dumps(self.health_fn(), separators=(",", ":"))
                    self.client.publish(self.topic, payload, qos=0, retain=False)
            except Exception as e:
                log.warning("mqtt publish failed: %s", e)

    def stop(self):
        self._stop.set()
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            pass


def start_mqtt(env: dict, health_fn: Callable[[], dict], interval_s: float = 5.0) -> MqttPublisher | None:
    if not truthy(get(env, "AGX_MQTT_ENABLED")) or not get(env, "AGX_MQTT_HOST"):
        log.info("mqtt disabled (AGX_MQTT_ENABLED!=1 or AGX_MQTT_HOST empty)")
        return None
    pub = MqttPublisher(env, health_fn, interval_s)
    pub.start()
    return pub
