#!/usr/bin/python3
# apt-get / zypper install python3-paho-mqtt
#
# nach /opt kopieren
#
# --install-systemd-service
# --clear-retain-config

import paho.mqtt.client as mqtt
import time
import sys
import re
#import os
#import shutil
import psutil
import subprocess
import json
#from subprocess import Popen, PIPE
import datetime
import os


MQTT_SERVER="home-assistant"
HOST_NAME="your-pc"
MAC="11:22:33:44:55:66"
# mit negative lookahead können verzeichnisse ausgeschlossen werden
MOUNTPOINT_REGEX="^\/(?!snap|dudl).*$"

OS_PRETTY_NAME="openSUSE Leap 15.5"

def getSmartCtlJson(device):
    cmd=['/usr/sbin/smartctl', '--info', '--xall', '--json', '--nocheck', 'standby', device]
    #proc = Popen(cmd, stdout=PIPE, stderr=PIPE, close_fds=True)
    completedProc = subprocess.run(cmd,  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    # print("stdout:" + completedProc.stdout.decode("utf-8"))

    #    _stdout, _stderr = [i for i in proc.communicate()]

    ret=json.loads(completedProc.stdout.decode("utf-8"))
    ret["exit_status"]=completedProc.returncode
    return ret


avail_topic="homeassistant/%s/avail" % (HOST_NAME)
def MQTT_connect():
    client = mqtt.Client()
    client.will_set(avail_topic, payload="offline", qos=2, retain=False)
    client.connect(MQTT_SERVER, 1883 , 60)
    client.loop_start()
    return client

def MQTT_register_sensor(client, entity_type, name, id, device_class, json_attributes=False, clear_retain=False):
    # retain -r << soll ma für config machen
    #\"json_attributes_path\": \"\$.result\",
    #\"state_value_template\":\"{{ value_json.smart_status}}\",
    #\"json_attributes\": [\"temperature\",\"model_name\"],
    topic="homeassistant/%s/%s/config" % (entity_type, id)
    print("register_sensor topic: %s" % topic)
    payload={
      "name": name,
      "device_class": device_class,
      "state_topic":"homeassistant/%s/%s/state" % (entity_type, id),
      "availability_topic":"%s" % avail_topic,
      "unique_id":"%s" % id,
      "device":{
        "identifiers":[
#            "name", HOST_NAME
#           "fritz", MAC
           MAC.upper(),
           OS_PRETTY_NAME
        ],
        "connections":[["mac",MAC]],
        "name":HOST_NAME
      }
    }
    if (json_attributes):
        payload["value_template"] = "{{ value_json.state}}"
        payload["json_attributes_topic"] = "homeassistant/%s/%s/state" % (entity_type, id)
        payload["json_attributes_template"] = "{{ value_json | tojson }}"
    if(device_class == "DATA_RATE"):
        payload["unit_of_measurement"] = "B/s"
    elif(device_class == "DATA_SIZE"):
        payload["unit_of_measurement"] = "B"
    elif(device_class == "BATTERY"):
        payload["unit_of_measurement"] = "%"
        payload["value_template"] = "{{ value_json.percent}}"

    if(clear_retain):
        print("clearing retain config")
        payload=""
    else:
        print("config: ", payload)
        payload=json.dumps(payload)
    client.publish(topic, payload=payload, retain=True)

def MQTT_online(client):
    client.publish(avail_topic, "online")

def sendData(client, entity_type, id, payload):

    print(json.dumps(payload))
    print("==================================================================")
    topic="homeassistant/%s/%s/state" % (entity_type, id)
    print("topic: %s" % topic)
    client.publish(topic, payload=json.dumps(payload))

def getSmartDevices():
    # return ['sda','sdb']
    cmd=["smartctl", "--scan", "--json"]
    completedProc = subprocess.run(cmd,  stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    ret=json.loads(completedProc.stdout.decode("utf-8"))
#    print("ret: ", ret)
    devices=[]
    for d in ret['devices']:
#        print("d:", d)
        devices.append(d['name'].replace('/dev/',''))

    print("monitoring devices: ", devices)
    return devices


def sendSmartData(client, device):
    jsonData=getSmartCtlJson("/dev/%s" % device)

    # print(json.dumps(jsonData))

    model_name=jsonData["model_name"]
    device_name=jsonData["device"]["name"]
    temperature=jsonData["temperature"]["current"]
    size=jsonData["user_capacity"]["bytes"]
    # upper case!!
    smart_status="ON" if jsonData["smart_status"]["passed"] == "true" else "OFF"

    smart_payload={"model_name":model_name,
        "device":device_name,
        "temperature":temperature,
        "size":size,
        "state":smart_status,
        "exit_status":jsonData['exit_status']
    }
    sendData(client, "binary_sensor", "%s_%s" % (HOST_NAME, device), smart_payload )

def cleanupPath(path):
    path=path[1:]
    if(path==''):
        ret="root"
    else:
        ret=path.replace("/","_")
    return ret

def sendPartitionUsage(client, partition):
    #total, used, free = shutil.disk_usage("/dev/%s" % DEVICE)
    #total, used, free, percent = shutil.disk_usage(partition)
    print(partition, psutil.disk_usage(partition).percent)
    #total, used, free = shutil.disk_usage(partition)
    total, used, free, percent = psutil.disk_usage(partition)
    print("total=%s, used=%s, free=%s %s%%" % (total, used, free, percent))
    payload={
        "size": total,
        "used": used,
        "free": free,
        "percent": percent,
    }
    id="%s_%s" % (HOST_NAME, cleanupPath(partition) )
    sendData(client, "sensor", id, payload )


def main():
    if (len(sys.argv) > 1) and (sys.argv[1] == "--install-systemd-service"):
        print("setting up systemd service")
        f = open("/etc/systemd/system/hw2ha.service", "w")
        f.write("""# by hw2ha.sh
[Unit]
Description=hw2ha sending hardware stats to home-assistant by MQTT
# Requires=network
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/opt/hw2ha.py
Restart=on-failure
#User=rygel
#Group=rygel

[Install]
WantedBy=default.target
""")
        f.close()
        os.system("systemctl daemon-reload")
        os.system("systemctl enable --now hw2ha")
        exit(0)

    clear_retain_config=False
    if (len(sys.argv) > 1) and (sys.argv[1] == "--clear-retain-config"):
        clear_retain_config=True

    client=MQTT_connect()

    MQTT_register_sensor(client, "sensor", "net traffice bytes_sent", "%s_net_%s" % (HOST_NAME, "bytes_sent"), "DATA_RATE", clear_retain=clear_retain_config)
    MQTT_register_sensor(client, "sensor", "net traffice bytes_recv", "%s_net_%s" % (HOST_NAME, "bytes_recv"), "DATA_RATE", clear_retain=clear_retain_config)

    block_devices=getSmartDevices()

    for device in block_devices:
        MQTT_register_sensor(client, "binary_sensor", "disk health %s" % device, "%s_%s" % (HOST_NAME, device), "problem", json_attributes=True, clear_retain=clear_retain_config)

    regex=re.compile(MOUNTPOINT_REGEX)
    mounted_filesystems=[]
    for p in psutil.disk_partitions():
        print("============ mountpoint %s" % p.mountpoint)
        if regex.match(p.mountpoint):
            print("register disk usage for %s" % p.mountpoint)
            # yes indeed battery for %
            MQTT_register_sensor(client, "sensor", "partition usage %s" % cleanupPath(p.mountpoint), "%s_%s" % (HOST_NAME, cleanupPath(p.mountpoint)), "BATTERY", json_attributes=True, clear_retain=clear_retain_config)
            mounted_filesystems.append(p)
        else:
            print("skipping disk usage for %s" % p.mountpoint)

    if(clear_retain_config):
        client.publish(avail_topic, payload='', retain=True)
        print("retain config cleared")
        exit(0)

    # home-assistant needs a second after new sensors have been published
    time.sleep(1)
    MQTT_online(client)

    for device in block_devices:
        sendSmartData(client, device)

    sleep_sec=10
    counters=psutil.net_io_counters()
    last_bytes_sent=counters.bytes_sent
    last_bytes_recv=counters.bytes_recv
    while True:
        #smart update everty 1 hour
        now = datetime.datetime.now()
        if now.minute == 0:
            for device in block_devices:
                sendSmartData(client, device)
        
        # network stats all together
        # pernic=True
        counters=psutil.net_io_counters()
        sendData(client, "sensor", "%s_net_%s" % (HOST_NAME, "bytes_sent"), (counters.bytes_sent-last_bytes_sent) / sleep_sec )
        sendData(client, "sensor", "%s_net_%s" % (HOST_NAME, "bytes_recv"), (counters.bytes_recv-last_bytes_recv) / sleep_sec )
        last_bytes_sent=counters.bytes_sent
        last_bytes_recv=counters.bytes_recv
        # =62749361, packets_sent=84311, packets_recv=94888, errin=0, errout=0, dropin=0, dropou


        # mounted filesystems disk size
        print(mounted_filesystems)
        for p in mounted_filesystems:
            print(p.device, p.mountpoint, psutil.disk_usage(p.mountpoint).percent)
            sendPartitionUsage(client, p.mountpoint)

        time.sleep(sleep_sec)

    client.loop_stop()

if __name__ == "__main__":
    main()
