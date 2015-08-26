#! /bin/bash

# tag 100 for control plane
ovs-vsctl --db=unix:/tmp/mininet-$1/db.sock set port $2 tag=100
ovs-ofctl add-flow $1 "priority=60001,in_port=$3,actions=NORMAL"
