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
import lib.agent_channel as scl

CONF_FILE = './conf/net.cfg'
config = ConfigParser.ConfigParser()
config.read(CONF_FILE)
agent_list = byteify(json.loads(config.get('interfaces', 'agent_list')))
proxy_list = byteify(json.loads(config.get('interfaces', 'proxy_list')))

sw_num = len(agent_list)

parser = argparse.ArgumentParser(description='Agent of Simple Coordinator Layer (SCL)')
parser.add_argument('sw_id', choices=range(0, sw_num), type=int, help='specify the switch id')
parser.add_argument('channel', choices=['tcp', 'udp'], default='udp', help='specify the channel type')
parser.add_argument('--log2file', action='store_true', help='store program log to file, dir is ./log/')
parser.add_argument('--debug', action='store_true', help='enable debug mode')
args = parser.parse_args()

LOG_FN = 'log/scl_agent_%s.log' % str(args.sw_id) \
        if args.log2file else None
LEVEL = logging.DEBUG if args.debug else logging.INFO
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y%m%d %H:%M:%S', level=LEVEL, filename=LOG_FN, filemode='w')
logger = logging.getLogger(__name__)

timer = Timer(logger)
streams = scl.Streams(logger)
selector = Selector()
scl2sw = scl.Scl2Sw(
        local_ctrl_host, local_ctrl_port, streams, logger)
if args.channel == 'udp':
    scl2scl = scl.Scl2SclUdp(
            streams, logger, agent_list[args.sw_id],
            scl_agent_port, scl_proxy_port)
else:
    scl2scl = scl.Scl2SclTcp(
            streams, logger, agent_list[args.sw_id],
            proxy_list, scl_proxy_port, timer)

timer.start()   # another thread, daemonize

while True:
    timer.wait(selector)
    scl2scl.wait(selector)
    scl2sw.wait(selector)
    lists = selector.block()
    timer.run(lists)
    scl2scl.run(lists)
    scl2sw.run(lists)
