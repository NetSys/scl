#! /bin/bash

cd ~/src-agent/scl-agent/
python scl_agent.py $1 tcp --debug > log/scl_agent_$1.log 2>&1 &
