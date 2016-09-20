#!/bin/bash

SW="$1"
INTFS=(`ifconfig | awk '/HWaddr/{print $1}'`)

ovs-vsctl --db=unix:/tmp/mininet-$SW/db.sock add-br $SW
# enable stp, disable default in-band hidden flows
ovs-vsctl --db=unix:/tmp/mininet-$SW/db.sock set Bridge $SW stp_enable=true
ovs-vsctl --db=unix:/tmp/mininet-$SW/db.sock set Bridge $SW other-config:disable-in-band=true
ovs-vsctl --db=unix:/tmp/mininet-$SW/db.sock set-fail-mode $SW standalone

for IF in ${INTFS[@]}; do
    echo $IF
    ovs-vsctl --db=unix:/tmp/mininet-$SW/db.sock add-port $SW $IF
done
