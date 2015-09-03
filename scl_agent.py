#! /usr/bin/python

import sys
import logging
from conf.const import *
from lib.selector import Selector
from lib.timer import Timer
import lib.agent_channel as channel


if len(sys.argv) is 3:
    sw_id = sys.argv[1]
    scl_agent_intf = sys.argv[2]

#LOG_FILENAME = 'log/scl_agent_%s.log' % str(sw_id)
LOG_FILENAME = None
LEVEL = logging.DEBUG    # DEBUG shows the whole states
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y%m%d %H:%M:%S', level=LEVEL, filename=LOG_FILENAME, filemode='w')
logger = logging.getLogger(__name__)

logger.debug('scl_agent_intf: %s' % scl_agent_intf)

timer = Timer(logger)
streams = channel.Streams()
scl2scl = channel.Scl2Scl(
        scl_agent_mcast_grp, scl_agent_mcast_port, scl_agent_intf,
        scl_proxy_mcast_grp, scl_proxy_mcast_port, timer, streams, logger)
scl2sw = channel.Scl2Sw(scl_agent_serv_host, scl_agent_serv_port, streams, logger)
selector = Selector()

timer.start()   # another thread, daemonize

while True:
    timer.wait(selector)
    scl2scl.wait(selector)
    scl2sw.wait(selector)
    lists = selector.block()
    timer.run(lists)
    scl2scl.run(lists)
    scl2sw.run(lists)
