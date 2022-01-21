# Sternenhimmel

Influence the light when the script is running:

    mosquitto_pub -t "sternenhimmel/group/b" -m '{"on": true, "amplitude": 1, "frequency": 0.5}' -r

## Deployment

    ssh pi@raspbee2.fd
    cd sternenhimmel
    git pull
    sudo systemctl restart sternenhimmel

## Pair device

Enable logging output

    sudo vim /etc/systemd/system/zigbee2mqtt.service
    sudo systemctl daemon-reload
    sudo systemctl restart zigbee2mqtt
    journalctl -fu zigbee2mqtt

Allow devices to join within 120 seconds: 

    mosquitto_pub -t "zigbee2mqtt/bridge/request/permit_join" -m '{"value": true, "time": 120}'

You should see the device ID. Use it to give your device a friendly name.

More details: https://www.zigbee2mqtt.io/guide/usage/pairing_devices.html

## Friendly names

Switches need to be named `switch/XXX`, whereby each X corresponds to a group named by letter X.
Brightness switches are named `switch/brightness/XXX`.
Frequency switches are named `switch/frequency/XXX`.

Lights need to be named `light/XN`, whereby X is the group (single letter) and N a number.

You can adjust the friendly names by editing the file `/opt/zigbee2mqtt/data/configuration.yaml`

OR, to avoid restarting the service, rename on the fly.
"from" can be friendly name or IEEE ID.
Change will be persisted to configuration file automatically.

    mosquitto_pub -t "zigbee2mqtt/bridge/request/device/rename" -m '{"from": "switch/c", "to": "switch/brightness/cd"}'
    # OR, use device ID
    mosquitto_pub -t "zigbee2mqtt/bridge/request/device/rename" -m '{"from": "0xec1bbdfffe59bc53", "to": "switch/frequency/ab"}'

