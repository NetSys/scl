#! /usr/bin/python

import sys
import logging
import argparse
import ConfigParser
import json
from conf.const import *
from lib.selector import Selector
from lib.timer import Timer
from lib.socket_utils import byteify
import lib.proxy_channel as scl

CONF_FILE = './conf/net.cfg'
config = ConfigParser.ConfigParser()
config.read(CONF_FILE)
agent_list = byteify(json.loads(config.get('interfaces', 'agent_list')))
proxy_list = byteify(json.loads(config.get('interfaces', 'proxy_list')))

ctrl_num = len(proxy_list)

parser = argparse.ArgumentParser(description='Proxy of Simple Coordinator Layer (SCL)')
parser.add_argument('ctrl_id', choices=range(0, ctrl_num), type=int, help='specify the controller id')
parser.add_argument('channel', choices=['tcp', 'udp'], default='udp', help='specify the channel type')
parser.add_argument('--fstats', action='store_true', help='enable flow stats to support te app')
parser.add_argument('--log2file', action='store_true', help='store program log to file, dir is ./log/')
parser.add_argument('--debug', action='store_true', help='enable debug mode')
args = parser.parse_args()

LOG_FN = 'log/scl_proxy_%s.log' % str(args.sw_id) \
        if args.log2file else None
LEVEL = logging.DEBUG if args.debug else logging.INFO
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y%m%d %H:%M:%S', level=LEVEL, filename=LOG_FN, filemode='w')
logger = logging.getLogger(__name__)

timer = Timer(logger)
streams = scl.Streams(ctrl_num, logger)
selector = Selector()
scl2ctrl = scl.Scl2Ctrl(
        local_ctrl_host, local_ctrl_port, timer, streams, logger)
if args.channel == 'udp':
    scl2scl = scl.Scl2SclUdp(
            scl2ctrl, timer, streams, logger, proxy_list, agent_list,
            proxy_list[args.ctrl_id], args.fstats, scl_proxy_port, scl_agent_port)
else:
    scl2scl = scl.Scl2SclTcp(
            scl2ctrl, timer, streams, logger, proxy_list, agent_list,
            proxy_list[args.ctrl_id], args.fstats, scl_proxy_port)

timer.start()   # another thread, daemonize

while True:
    timer.wait(selector)
    scl2ctrl.wait(selector)
    scl2scl.wait(selector)
    lists = selector.block()
    timer.run(lists)
    scl2ctrl.run(lists)
    scl2scl.run(lists)
