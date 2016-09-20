#! /bin/bash

IP_ADDRS=( 10.1.0.1 10.1.1.1 10.1.2.1 10.1.4.1 10.1.5.1  10.1.6.1 10.1.9.1 10.1.10.1 10.1.11.1 10.1.12.1 10.1.13.1 10.1.14.1 )
for IP in "${IP_ADDRS[@]}"
do
    ping -c 1 $IP > /dev/null 2>&1
    ret=$?
    if [ $ret != 0 ]; then
        echo "$IP unreachable"
    else
        echo "$IP works"
    fi
done
