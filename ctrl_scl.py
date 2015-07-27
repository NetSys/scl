#! /usr/bin/python

import logging
from lib.const import *
import lib.scl_channel as scl


LOG_FILENAME = None
LEVEL = logging.DEBUG    # DEBUG shows the whole states
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y%m%d %H:%M:%S', level=LEVEL, filename=LOG_FILENAME)
logger = logging.getLogger(__name__)

streams = scl.Streams()
scl2ctrl = scl.Scl2Ctrl(ctrl_host, ctrl_port, streams, logger)
scl2scl = scl.Scl2Scl(
        ctrl_scl_mcast_grp, ctrl_scl_mcast_port,
        ctrl_scl_intf, scl2ctrl, streams, logger)

selector = scl.Selector()

while True:
    scl2ctrl.wait(selector)
    scl2scl.wait(selector)
    lists = selector.block()
    scl2ctrl.run(lists)
    scl2scl.run(lists)
