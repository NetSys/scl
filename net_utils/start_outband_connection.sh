#!/bin/bash

SW="$1"
OUTPORT=$2

ovs-vsctl --db=unix:/tmp/mininet-$SW/db.sock set-controller $SW tcp:127.0.0.1:6633

# flow entries added before set-controller would be flushed
ovs-ofctl add-flow $SW "priority=60001,in_port=LOCAL,actions=$OUTPORT"
ovs-ofctl add-flow $SW "priority=60001,in_port=$OUTPORT,actions=LOCAL"
