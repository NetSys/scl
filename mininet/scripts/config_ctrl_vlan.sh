#! /bin/bash

SW="$1"

# tag 100 for control plane
ovs-vsctl --db=unix:/tmp/mininet-$SW/db.sock set bridge $SW protocols=OpenFlow10,OpenFlow12,OpenFlow13

ovs-ofctl -O OpenFlow13 add-flow $SW "priority=60010,in_port=$3,actions=local"
ovs-ofctl -O OpenFlow13 add-flow $SW "priority=60010,in_port=local,actions=output:$3,mod_vlan_vid:100,output:$4,output:$5,output:$6"

ovs-vsctl --db=unix:/tmp/mininet-$SW/db.sock set bridge $SW protocols=OpenFlow10
