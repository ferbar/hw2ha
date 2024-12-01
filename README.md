# HW2HA - Hardware to Home-Assistant by MQTT

### Sensors for
* Smart errors
* CPU load
* Memory usage
* Disk usage
* Network traffic rx/tx

![Home-Assistant disk sensor](doc/home_assistant_sensors.png)

![Home-Assistant disk sensor](doc/home_assistant_harddisk.png)


### Installation

copy hw2ha.py to /opt/

`apt-get / zypper install python3-paho-mqtt`

`hw2ha.py --install-systemd-service` to install systemd service

`systemct enable --now hw2ha`

`hw2ha.py --clear-retain-config` to clean up Home-Assistant entities


### Config:

`MQTT_SERVER="home-assistant"`

## Home-Assistant Smart Register Alert

copy hw2ha_smart_failed.yaml to .homeassistant/packages/

```
alias: Linux PC HD Smart Register
description: ""
trigger:
  - platform: state
    entity_id:
      - binary_sensor.hw2ha_smart_register_failed
    to: null
    for:
      hours: 0
      minutes: 1
      seconds: 0
condition: []
action:
  - service: notify.persistent_notification
    metadata: {}
    data:
      title: Check harddisks!!!
      message: >-
        smart register failed! Problem: {{trigger.to_state.state}} Errors:
        {{trigger.to_state.attributes.devices.errors}}
mode: single

```
