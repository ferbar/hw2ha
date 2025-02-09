#!/usr/bin/python3
# apt-get / zypper install python3-paho-mqtt python3-psutil
#
# INSTALLATION:
#
# --install-systemd-service
#
# cleanup entities:
# --clear-retain-config
#
# reconnect: https://www.emqx.com/en/blog/how-to-use-mqtt-in-python
# hint: reconnect testen mit `ss -K -tp '( dport = :1883  )'`
#
# Config via environment (=>/opt/hw2ha.conf)
#     DISABLE_SMARTCTL=y
#
# counter for netfilter rules: EXPR from
#                                         nft --json list chain filter INPUT | jq
#
#     NFT_COUNTER\d+_EXPR='ip.saddr == 192.168.0.0/16; tcp.dport == 443'
#     NFT_COUNTER\d+_NAME=nft_XXXXXX
#
#


import paho.mqtt.client as mqtt_client
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
import socket
import glob
from pathlib import Path


DISABLE_SMARTCTL=os.environ.get("DISABLE_SMARTCTL", False)

MQTT_SERVER=os.environ.get("MQTT_SERVER", "home-assistant")
# remove domain
HOST_NAME=socket.gethostname().split('.')[0]
# get from nic
MAC=os.environ.get("MAC", False)
# mit negative lookahead können verzeichnisse ausgeschlossen werden
MOUNTPOINT_REGEX="^\/(?!snap|foodevice).*$"

DEBUG=os.environ.get("DEBUG", False)

# get from /etc/os_release
OS_PRETTY_NAME=False

# on start and when home-assistant has been restarted
SEND_ALL=True

class bcolors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    FAIL = '\033[91m'
    DEFAULT = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def debug(*args):
    if DEBUG:
        print(*args)

def info(*args):
    print(bcolors.YELLOW, *args, bcolors.DEFAULT)

def warn(*args):
    print(bcolors.RED, *args, bcolors.DEFAULT, file=sys.stderr)

def error(*args):
    print(bcolors.RED, *args, bcolors.DEFAULT, file=sys.stderr)

def set_MAC():
    global MAC
    global OS_PRETTY_NAME
    info("getting MAC")
    # get MAC address:
    if MAC == False:
      #print(psutil.net_if_addrs())
      for nic_name, nic in psutil.net_if_addrs().items():
        debug("key:", nic_name)
        if nic_name=='lo':
          continue
        #print("nic:", nic)
        # net interface up?
        if socket.AF_INET in [snicaddr.family for snicaddr in nic] :
          debug("~~~~ using MAC address of %s" % nic_name)
          #print(nic)
          phy=[snicaddr.address for snicaddr in nic if socket.AF_PACKET == snicaddr.family ]
          debug(phy)
          MAC=phy[0] or False
          break
    if MAC == False:
        warn("Error: MAC not found!")
    info("Hostname:", HOST_NAME)
    info("MAC:", MAC)

    file_path = '/etc/os-release'

    with open(file_path, 'r') as file:
        file_content = file.read()
        debug(file_content)
        x = re.findall("^PRETTY_NAME=\"(.*)\"$", file_content, re.MULTILINE)
        OS_PRETTY_NAME=x[0]
    info(OS_PRETTY_NAME)


def getSmartCtlJson(device):
    cmd=['/usr/sbin/smartctl', '--info', '--xall', '--json', '--nocheck', 'standby', device]
    #proc = Popen(cmd, stdout=PIPE, stderr=PIPE, close_fds=True)
    completedProc = subprocess.run(cmd,  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    # print("stdout:" + completedProc.stdout.decode("utf-8"))

    #    _stdout, _stderr = [i for i in proc.communicate()]

    ret=json.loads(completedProc.stdout.decode("utf-8"))
    ret["exit_status"]=completedProc.returncode
    return ret


def on_disconnect(client, userdata, rc):
    warn("=============MQTT disconnected=================")

# send 'online' in case of reconnect
def on_connect(client, userdata, flags, rc):
    info("=============MQTT connected userdata:", userdata, " flags: ", flags, " rc:", rc)
    MQTT_online(client)

# client does auto-reconnect on it's own
avail_topic="homeassistant/%s/avail" % (HOST_NAME)
def MQTT_connect():
    client = mqtt_client.Client()
    client.will_set(avail_topic, payload="offline", qos=2, retain=False)
    client.on_disconnect = on_disconnect
    client.on_connect = on_connect
    client.connect(MQTT_SERVER, 1883 , 60)
    client.loop_start()
    return client

def MQTT_register_sensor(client: mqtt_client, entity_type, name, id, device_class, json_attributes=False, clear_retain=False):
    # retain -r << soll ma für config machen
    #\"json_attributes_path\": \"\$.result\",
    #\"state_value_template\":\"{{ value_json.smart_status}}\",
    #\"json_attributes\": [\"temperature\",\"model_name\"],
    topic="homeassistant/%s/%s/config" % (entity_type, id)
    print("register_sensor topic: %s" % topic)
    payload={
      "name": name,
      "state_topic":"homeassistant/%s/%s/state" % (entity_type, id),
      "availability_topic":"%s" % avail_topic,
      "unique_id":"%s" % id,
      "device":{
        "identifiers":[
#            "name", HOST_NAME
#           "fritz", MAC
           MAC.upper(),
        ],
        "model": OS_PRETTY_NAME,
        "connections":[["mac",MAC]],
        "name":HOST_NAME
      }
    }

    if (json_attributes):
        payload["value_template"] = "{{ value_json.state}}"
        payload["json_attributes_topic"] = "homeassistant/%s/%s/state" % (entity_type, id)
        payload["json_attributes_template"] = "{{ value_json | tojson }}"

    if(device_class=='CPU'):
        payload['icon']='mdi:cpu-64-bit'
        payload['state_class']='MEASUREMENT'
    elif(device_class == "NET_SENT"):
        payload["unit_of_measurement"] = "B/s"
        payload['icon']='mdi:upload_network'
    elif(device_class == "NET_RECV"):
        payload["unit_of_measurement"] = "B/s"
        payload['icon']='mdi:download_network'
    elif(device_class == "DATA_SIZE"):
        payload["unit_of_measurement"] = "B"
        payload['icon']='mdi:memory'
    elif(device_class == "DISK"):
        payload["unit_of_measurement"] = "%"
        payload["value_template"] = "{{ value_json.percent}}"
        payload['icon']='mdi:harddisk'
    elif(device_class):
        payload['device_class']=device_class

    if(clear_retain):
        info("clearing retain config")
        payload=""
    else:
        info("config: ", payload)
        payload=json.dumps(payload)
    client.publish(topic, payload=payload, retain=True)

def MQTT_online(client: mqtt_client):
    info("=============MQTT online")
    client.publish(avail_topic, "online", retain=True)

def MQTT_subscribe_ha_restart(client: mqtt_client):
    def on_message(client, userdata, msg):
        payload=msg.payload.decode()
        info(f"Received `{payload}` from `{msg.topic}` topic")
        global SEND_ALL
        if payload == "online":
            info("MQTT_subscribe_ha_restart: HA online message received")
            SEND_ALL=True

    DEFAULT_STATUS_TOPIC = 'homeassistant/status'
    client.subscribe(DEFAULT_STATUS_TOPIC)
    status_topic = 'hass/status'
    client.subscribe(status_topic)
    client.on_message = on_message

def sendData(client: mqtt_client, entity_type, id, payload):

    debug(json.dumps(payload))
    debug("==================================================================")
    topic="homeassistant/%s/%s/state" % (entity_type, id)
    debug("topic: %s" % topic)
    client.publish(topic, payload=json.dumps(payload))

def getSmartDevices():
    # return ['sda','sdb']
    info(getSmartDevices)
    cmd=["smartctl", "--scan", "--json"]
    completedProc = subprocess.run(cmd,  stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    ret=json.loads(completedProc.stdout.decode("utf-8"))
#    print("ret: ", ret)
    devices=[]
    for d in ret['devices']:
        debug("d:", d, " name:",d['name'])
        skip=False
        for usbdir in glob.glob('/dev/disk/by-id/usb-*'):
            usb_dev_path=Path(usbdir).resolve()
            debug("~~~~", usb_dev_path, d['name'])
            if str(usb_dev_path) == str(d['name']):
                info("SKIPPING USB DISK (%s)" % d)
                skip=True
        if not skip:
            debug("add disk", d['name'])
            devices.append(d['name'].replace('/dev/',''))

    info("monitoring devices: ", devices)
    return devices


def sendSmartData(client: mqtt_client, device):
    jsonData=getSmartCtlJson("/dev/%s" % device)

    # print(json.dumps(jsonData))

    model_name=jsonData["model_name"]
    device_name=jsonData["device"]["name"]
    temperature=jsonData["temperature"]["current"]
    size=jsonData["user_capacity"]["bytes"]

    exit_status=int(jsonData['exit_status'])
    # bit 2
    # some smart command failed / not supported
    # bit 7
    device_error_log=exit_status & (1 << 7)
    # bit 8
    selftest_error_log=exit_status & (1 << 8)

    smart_status_error=jsonData["smart_status"]["passed"] != True

    # upper case!!
    problem="ON" if device_error_log or selftest_error_log or smart_status_error else "OFF"

    smart_payload={
        "model_name": model_name,
        "device": device_name,
        "temperature": temperature,
        "size": size,
        "state": problem,
        "exit_status": exit_status,
        "device_error_log": device_error_log,
        "selftest_error_log": selftest_error_log,
        "smart_status_error": smart_status_error
    }
    sendData(client, "binary_sensor", "%s_%s" % (HOST_NAME, device), smart_payload )

def cleanupPath(path):
    path=path[1:]
    if(path==''):
        ret="root"
    else:
        ret=path.replace("/","_")
    return ret

def sendPartitionUsage(client: mqtt_client, partition):
    #total, used, free = shutil.disk_usage("/dev/%s" % DEVICE)
    #total, used, free, percent = shutil.disk_usage(partition)
    debug(partition, psutil.disk_usage(partition).percent)
    #total, used, free = shutil.disk_usage(partition)
    total, used, free, percent = psutil.disk_usage(partition)
    debug("total=%s, used=%s, free=%s %s%%" % (total, used, free, percent))
    payload={
        "size": total,
        "used": used,
        "free": free,
        "percent": percent,
    }
    id="%s_%s" % (HOST_NAME, cleanupPath(partition) )
    sendData(client, "sensor", id, payload )

def netfilterMatch2String(expr):
    ret=""
    last_ret="";
    for e in expr:
        if ret!=last_ret:
            ret+='; '
        last_ret=ret;
        if "match" in e:
            # FIXME: implement --dports ... dport={1,2,3}
            ret+="%s.%s %s " % (e["match"]["left"]["payload"]["protocol"], e["match"]["left"]["payload"]["field"],e["match"]["op"])
            if type(e["match"]["right"]) == str or type(e["match"]["right"]) == int:
                ret+="%s" % e["match"]["right"]
            else:
                ret+="%s/%s" % ( e["match"]["right"]["prefix"]["addr"], e["match"]["right"]["prefix"]["len"])
        elif "accept" in e:
            ret+="accept "
        elif "drop" in e:
            ret+="drop "
        elif "jump" in e:
            ret+="jump "+e["jump"]["target"]
    return ret.strip()



def main():
    set_MAC()

    if (len(sys.argv) > 1) and (sys.argv[1] == "--install-systemd-service"):
        info("setting up systemd service")
        f = open("/etc/systemd/system/hw2ha.service", "w")
        f.write("""# by hw2ha.py
[Unit]
Description=hw2ha sending hardware stats to home-assistant by MQTT
# Requires=network
After=network-online.target
Wants=network-online.target

[Service]
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=-/opt/hw2ha.conf
ExecStart=/opt/hw2ha.py
Restart=on-failure
#User=XYZ
#Group=XYZ

[Install]
WantedBy=default.target
""")
        f.close()
        os.system("systemctl daemon-reload")
        os.system("systemctl enable --now hw2ha")
        warn("copy or softlink $0 to /opt/hw2ha.py by yourself pls")
        exit(0)

    clear_retain_config=False
    if (len(sys.argv) > 1) and (sys.argv[1] == "--clear-retain-config"):
        clear_retain_config=True

    client=MQTT_connect()

    MQTT_register_sensor(client, "sensor", "cpu load", "%s_cpu" % (HOST_NAME), 'CPU', clear_retain=clear_retain_config)
    MQTT_register_sensor(client, "sensor", "memory usage", "%s_memory" % (HOST_NAME), "DATA_SIZE", clear_retain=clear_retain_config)

# network stats all together ======================================================================
    MQTT_register_sensor(client, "sensor", "net traffic bytes_sent", "%s_net_%s" % (HOST_NAME, "bytes_sent"), "NET_SENT", clear_retain=clear_retain_config)
    MQTT_register_sensor(client, "sensor", "net traffic bytes_recv", "%s_net_%s" % (HOST_NAME, "bytes_recv"), "NET_RECV", clear_retain=clear_retain_config)

# smartctl ========================================================================================
    if (not DISABLE_SMARTCTL):
        print("DISABLE_SMARTCTL:", DISABLE_SMARTCTL)
        block_devices=getSmartDevices()
    else:
        warn("smartctl checking disabled")
        block_devices=[]

    for device in block_devices:
        MQTT_register_sensor(client, "binary_sensor", "disk health %s" % device, "%s_%s" % (HOST_NAME, device), "problem", json_attributes=True, clear_retain=clear_retain_config)

# partition usage =================================================================================
    regex=re.compile(MOUNTPOINT_REGEX)
    mounted_filesystems=[]
    for p in psutil.disk_partitions():
        info("============ mountpoint %s" % p.mountpoint)
        if regex.match(p.mountpoint):
            print("register disk usage for %s" % p.mountpoint)
            # yes indeed battery for %
            MQTT_register_sensor(client, "sensor", "partition usage %s" % cleanupPath(p.mountpoint), "%s_%s" % (HOST_NAME, cleanupPath(p.mountpoint)), "DISK", json_attributes=True, clear_retain=clear_retain_config)
            mounted_filesystems.append(p)
        else:
            warn("skipping disk usage for %s" % p.mountpoint)

# NETFILER filters ================================================================================
    n=0
    netfilter_counter={}
    empty=0
    while True:
        print("looking for NFT_COUNTER%s_NAME" %n)
        if os.environ.get("NFT_COUNTER%s_NAME" %n, False):
            info("netfilter_counter: [" + ("NFT_COUNTER%s_NAME" %n) + " = "+os.environ.get("NFT_COUNTER%s_NAME" %n)+"] = " + ("NFT_COUNTER%s_EXPR" %n)+ "="+os.environ.get("NFT_COUNTER%s_EXPR" %n))
            counter_name=os.environ.get("NFT_COUNTER%s_NAME" %n)
            counter_expr=os.environ.get("NFT_COUNTER%s_EXPR" %n)
            netfilter_counter[counter_name] = {"last_sent":None, "expr":counter_expr}
            MQTT_register_sensor(client, "sensor", "net traffic filter %s" % counter_name, "%s_net_%s" % (HOST_NAME, counter_name), "NET_SENT", clear_retain=clear_retain_config)
        else:
            empty+=1
        n+=1
        if (empty > 3):
            break


    if(clear_retain_config):
        client.publish(avail_topic, payload='', retain=True)
        info("retain config cleared")
        exit(0)

    # home-assistant needs a second after new sensors have been published
    time.sleep(1)
    # nachdem wir die config geschickt haben nocheinmal die online message ...
    MQTT_online(client)
    MQTT_subscribe_ha_restart(client)

    sleep_sec=10
    counters=psutil.net_io_counters()
    last_bytes_sent=counters.bytes_sent
    last_bytes_recv=counters.bytes_recv
    global SEND_ALL
    last_send_all=time.time()

    while True:
        #smart update everty 1 hour
        now = time.time()
        if last_send_all + 3600 < now:
            SEND_ALL=True

# smartctl ========================================================================================
        if SEND_ALL:
            SEND_ALL=False
            last_send_all=now
            for device in block_devices:
                sendSmartData(client, device)
        
        load1, load5, load15 = psutil.getloadavg()
        sendData(client, "sensor", "%s_cpu" % (HOST_NAME), load1 )
        #sendData(client, "sensor", "%s_memory" % (HOST_NAME), psutil.virtual_memory()[3]/1000000000 )
        sendData(client, "sensor", "%s_memory" % (HOST_NAME), psutil.virtual_memory()[3] )

# network stats all together ======================================================================
        counters=psutil.net_io_counters()
        sendData(client, "sensor", "%s_net_%s" % (HOST_NAME, "bytes_sent"), (counters.bytes_sent-last_bytes_sent) / sleep_sec )
        sendData(client, "sensor", "%s_net_%s" % (HOST_NAME, "bytes_recv"), (counters.bytes_recv-last_bytes_recv) / sleep_sec )
        last_bytes_sent=counters.bytes_sent
        last_bytes_recv=counters.bytes_recv
        # =62749361, packets_sent=84311, packets_recv=94888, errin=0, errout=0, dropin=0, dropou


# partition usage =================================================================================
        regex=re.compile(MOUNTPOINT_REGEX)
        debug(mounted_filesystems)
        for p in mounted_filesystems:
            debug(p.device, p.mountpoint, psutil.disk_usage(p.mountpoint).percent)
            sendPartitionUsage(client, p.mountpoint)

        time.sleep(sleep_sec)

# NETFILER filters ================================================================================
        if len(netfilter_counter) > 0:
            cmd=["nft", "--json", "list", "chain", "filter", "INPUT"]
            completedProc = subprocess.run(cmd,  stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            jsonData=json.loads(completedProc.stdout.decode("utf-8"))
            for entry in jsonData['nftables']:
                #print("entry", json.dumps(entry))
                has_counter=False
                if "rule" in entry:
                    #print("is rule")
                    expr=netfilterMatch2String(entry["rule"]["expr"])
                    #print(">>>%s<<<" % expr)
                    for counter_name in netfilter_counter:
                        if expr == netfilter_counter[counter_name]["expr"]:
                            debug("found name: %s=%s" % (counter_name, expr))
                            for e in entry["rule"]["expr"]:
                                if "counter" in e:
                                    last_sent=netfilter_counter[counter_name]["last_sent"]
                                    #print("has counter pkg: %d, byted: %d" %( e["counter"]["packets"], e["counter"]["bytes"] ))
                                    counter_value=e["counter"]["bytes"]
                                    if last_sent == None:
                                        debug("didn't send data yet, skipping")
                                    else:
                                        sendData(client, "sensor", "%s_net_%s" % (HOST_NAME, counter_name), (counter_value - last_sent) / sleep_sec )
                                    netfilter_counter[counter_name]["last_sent"]=counter_value
                                    break

# =============================================================================================
    client.loop_stop()

if __name__ == "__main__":
    main()
