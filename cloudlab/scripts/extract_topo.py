#! /usr/bin/python

import json
import subprocess


ssh_sw_file = '../conf/ssh_sw'
ssh_sws_raw = []
ssh_host_file = '../conf/ssh_host'
ssh_hosts_raw = []

ips_file = '../conf/ips'
topo_file = '../conf/fattree_outband_cloudlab.json'

intfs = ['eth1', 'eth2', 'eth3', 'eth4']
sw_intf_to_ip = {}
ips_raw = []
topo = {'hosts': {}, 'links': []}

with open(ssh_sw_file) as f:
    for i in f.readlines():
        ret = i.split(' ')
        ret[-1] = ret[-1][0: len(ret[-1])-1]
        ssh_sws_raw.append(ret)

with open(ssh_host_file) as f:
    for i in f.readlines():
        ret = i.split(' ')
        ret[-1] = ret[-1][0: len(ret[-1])-1]
        ssh_hosts_raw.append(ret)

sl = len(ssh_sws_raw)
for i in range(0, sl):
    print 'switch %d' % i
    ret = ssh_sws_raw[i]
    for intf in intfs:
        sw_intf_to_ip[('s'+str(i).zfill(3), intf)] = subprocess.check_output("ssh -o StrictHostKeyChecking=no -i your_key -p %s %s sudo ifconfig %s 2>/dev/null|awk '/inet addr:/ {print $2}'|sed 's/addr://'" % (ret[2], ret[3], intf), shell=True)

hl = len(ssh_hosts_raw)
for i in range(0, hl):
    print 'host %d' % i
    ret = ssh_hosts_raw[i]
    sw_intf_to_ip[('h'+str(i).zfill(3), 'eth1')] = subprocess.check_output("ssh -o StrictHostKeyChecking=no -i your_key -p %s %s sudo ifconfig eth1 2>/dev/null|awk '/inet addr:/ {print $2}'|sed 's/addr://'" % (ret[2], ret[3]), shell=True)

for sw, intf in sw_intf_to_ip.keys():
    ip = sw_intf_to_ip[(sw, intf)]
    ip = ip[0: len(ip) - 1]
    sw_intf_to_ip[(sw, intf)] = ip

print sw_intf_to_ip

for sw1, intf1 in sw_intf_to_ip.keys():
    if (sw1, intf1) not in sw_intf_to_ip:
        continue
    ip1 = sw_intf_to_ip[(sw1, intf1)]
    ret = ip1.split('.')
    id1 = ret[0] + ret[1] + ret[2]
    del sw_intf_to_ip[(sw1, intf1)]
    for sw2, intf2 in sw_intf_to_ip.keys():
        ip2 = sw_intf_to_ip[(sw2, intf2)]
        ret = ip2.split('.')
        id2 = ret[0] + ret[1] + ret[2]
        if id1 == id2:
            port1, port2 = int(intf1[-1]), int(intf2[-1])
            topo['links'].append([sw1, intf1, port1, sw2, intf2, port2])
            del sw_intf_to_ip[(sw2, intf2)]
            break

with open(ips_file) as ipf:
    for i in ipf.readlines():
        ips_raw.append(i)

for ip_raw in ips_raw:
    ret = ip_raw.split(' ')
    sw, intf = ret[1].split(':')
    id = int(sw.split('-')[1])
    if id >= 20:
        host = 'h' + str(id - 20).zfill(3)
        ret[-1] = ret[-1][0: len(ret[-1]) - 1]
        topo['hosts'][host] = ret[-1]

with open(topo_file, 'wb') as tf:
    json.dump(topo, tf)
