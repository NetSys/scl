#!/bin/bash

SW="$1"

ovs-vsctl --db=unix:/tmp/mininet-$SW/db.sock set-controller $SW tcp:127.0.0.1:6633
ovs-vsctl --db=unix:/tmp/mininet-$SW/db.sock set bridge $SW protocols=OpenFlow10,OpenFlow12,OpenFlow13

# flow entries added before set-controller would be flushed
ovs-ofctl -O OpenFlow13 add-flow $SW "priority=60002,in_port=local,actions=mod_vlan_vid:100,flood"
ovs-ofctl -O OpenFlow13 add-flow $SW "priority=60001,dl_vlan=100,actions=strip_vlan,local"

ovs-vsctl --db=unix:/tmp/mininet-$SW/db.sock set bridge $SW protocols=OpenFlow10
