#!/bin/bash

SW="$1"
INTFS=(`ifconfig | awk '/HWaddr/{print $1}'`)

ovs-vsctl --db=unix:/tmp/mininet-$SW/db.sock add-br $SW
# disable stp, disable default in-band hidden flows
ovs-vsctl --db=unix:/tmp/mininet-$SW/db.sock set Bridge $SW other-config:disable-in-band=true
ovs-vsctl --db=unix:/tmp/mininet-$SW/db.sock set-fail-mode $SW secure

for IF in ${INTFS[@]}; do
    echo $IF
    ovs-vsctl --db=unix:/tmp/mininet-$SW/db.sock add-port $SW $IF
done

# change ip addr to internal port and add default route to forward broadcast msg
BR_ADDR=`ifconfig $SW-eth0 2>/dev/null|awk '/inet addr:/ {print $2}'|sed 's/addr://'`
ifconfig $SW-eth0 0
ifconfig $SW $BR_ADDR
route add default gw $BR_ADDR
