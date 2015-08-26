#!/bin/bash

SW="$1"

ovs-vsctl --db=unix:/tmp/mininet-$SW/db.sock set-controller $SW tcp:127.0.0.1:6633

# flow entries added before set-controller would be flushed
ovs-ofctl add-flow $SW "priority=60001,in_port=LOCAL,actions=NORMAL"
ovs-ofctl add-flow $SW "priority=60001,dl_vlan=100,actions=NORMAL"
ovs-ofctl add-flow $SW "priority=60000,arp,actions=NORMAL"
