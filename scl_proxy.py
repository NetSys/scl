#! /usr/bin/python

import logging
from lib.const import *
from lib.selector import Selector
from lib.timer import Timer
from lib.gossiper import Gossiper
import lib.proxy_channel as scl


LOG_FILENAME = None
LEVEL = logging.DEBUG    # DEBUG shows the whole states
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y%m%d %H:%M:%S', level=LEVEL, filename=LOG_FILENAME)
logger = logging.getLogger(__name__)

timer = Timer(logger)
streams = scl.Streams(host_id, peer_lists)
scl2ctrl = scl.Scl2Ctrl(ctrl_host, ctrl_port, streams, logger)
scl2scl = scl.Scl2Scl(
        scl_proxy_mcast_grp, scl_proxy_mcast_port,
        scl_proxy_intf, scl2ctrl, timer, streams, logger)
gossiper = Gossiper(
        scl_gossip_mcast_grp, scl_gossip_mcast_port, scl_gossip_intf,
        host_id, peer_lists, timer, streams, logger)
selector = Selector()

timer.start()   # another thread, daemonize

while True:
    timer.wait(selector)
    scl2ctrl.wait(selector)
    scl2scl.wait(selector)
    gossiper.wait(selector)
    lists = selector.block()
    timer.run(lists)
    scl2ctrl.run(lists)
    scl2scl.run(lists)
    gossiper.run(lists)
