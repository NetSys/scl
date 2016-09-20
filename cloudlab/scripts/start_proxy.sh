#! /bin/bash

cd ~/src-proxy/scl-proxy/

python pox/pox.py log.level --DEBUG log --format="%(asctime)s.%(msecs)03d - %(name)s - %(levelname)s - %(message)s" --datefmt="%Y%m%d %H:%M:%S" scl_routing --name="./conf/fattree_outband_cloudlab.json" > log/ctrl_$1.log 2>&1 &

sleep 5

python scl_proxy.py $1 tcp > log/scl_proxy_$1.log 2>&1 &
