#! /usr/bin/python

import logging
from lib.const import *
from lib.selector import Selector
import lib.agent_channel as channel


LOG_FILENAME = None
LEVEL = logging.DEBUG    # DEBUG shows the whole states
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y%m%d %H:%M:%S', level=LEVEL, filename=LOG_FILENAME)
logger = logging.getLogger(__name__)

streams = channel.Streams()
scl2scl = channel.Scl2Scl(scl_proxy_mcast_grp, scl_proxy_mcast_port, streams, logger)
scl2sw = channel.Scl2Sw(scl_agent_serv_host, scl_agent_serv_port, streams, logger)
selector = Selector()

while True:
    scl2scl.wait(selector)
    scl2sw.wait(selector)
    lists = selector.block()
    scl2scl.run(lists)
    scl2sw.run(lists)
