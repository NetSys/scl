#! /usr/bin/python

import subprocess

ssh_sw_file = '../conf/ssh_sw'
ssh_sws_raw = []

with open(ssh_sw_file) as f:
    for i in f.readlines():
        ret = i.split(' ')
        ret[-1] = ret[-1][0: len(ret[-1])-1]
        ssh_sws_raw.append(ret)

l = len(ssh_sws_raw)

for i in range(0, l):
    print 'switch %d' % i
    ret = ssh_sws_raw[i]
    subprocess.call("ssh -o StrictHostKeyChecking=no -i your_key -p %s %s sudo ./start_agent.sh %d" % (ret[2], ret[3], i), shell=True)
