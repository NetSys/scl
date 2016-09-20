#! /bin/bash

PIDS=(`ps -ef | grep pox | awk '{print $2}'`)

for PID in ${PIDS[@]}; do
    kill -9 $PID > /dev/null 2>&1
done

PIDS=(`ps -ef | grep scl | awk '{print $2}'`)

for PID in ${PIDS[@]}; do
    kill -9 $PID > /dev/null 2>&1
done
