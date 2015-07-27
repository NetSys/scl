#! /usr/bin/python

import Queue
import select
import socket
import logging
import json
from lib.const import *
from lib.socket_utils import *
from lib.libopenflow_01 import ofp_port_status
import lib.scl_protocol as scl


upstream = Queue.Queue()
downstream = Queue.Queue()

udp_conn = UdpConn(ctrl_scl_mcast_grp, ctrl_scl_mcast_port)
udp_conn.open()

tcp_serv = TcpListen(sw_scl_serv_host, sw_scl_serv_port)
tcp_serv.open()

ovsdb_conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
ovsdb_conn.connect(OVSDB)   # check the OVSDB path
db_link_state_query = {"method": "", "params": [], "id": 0}

inputs = [udp_conn.sock, tcp_serv.sock]
outputs = [udp_conn.sock]

LOG_FILENAME = None
LEVEL = logging.DEBUG    # DEBUG shows the whole states
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y%m%d %H:%M:%S', level=LEVEL, filename=LOG_FILENAME)
logger = logging.getLogger(__name__)


def adjust_outputs(outputs, udp_conn, tcp_client, upstream, downstream):
    '''
    when stream is empty, remove the corresponding socket from outputs
    if writeable socket is put in outputs directly, select will be called
    more frequentlty and the cpu usage may be 100%.
    '''
    if upstream.empty() and udp_conn.sock in outputs:
        outputs.remove(udp_conn.sock)
    elif not upstream.empty() and udp_conn.sock not in outputs:
        outputs.append(udp_conn.sock)
    if tcp_client:
        if downstream.empty() and tcp_client in outputs:
            outputs.remove(tcp_client)
        elif not downstream.empty() and tcp_client not in outputs:
            outputs.append(tcp_client)


def handle_of_msg(upstream, data):
    '''
    parse of link state
    put data into upstream
    '''
    upstream.put(scl.addheader(data, scl.SCLT_OF))
    offset = 0
    data_length = len(data)
    logger.debug('data_length: %d' % data_length)
    # parse multiple of msgs in one data
    while data_length - offset >= 8:
        of_type = ord(data[offset + 1])
        msg_length = ord(data[offset + 2]) << 8 | ord(data[offset + 3])
        logger.debug('msg_length: %d' % msg_length)
        if data_length - offset < msg_length:
            break

        if of_type == 12:
            port_status = ofp_port_status()
            port_status.unpack(data[offset: offset + msg_length])
            logger.info(
                '%s %d' % (port_status.desc.name, port_status.desc.state))
            link_state = scl.scl_link_state()
            msg = link_state.pack(port_status.desc.name, port_status.desc.state)
            upstream.put(scl.addheader(msg, scl.SCLT_LINK_RPLY))

        offset = offset + msg_length


def tcp_close(sock, inputs, outputs, upstream):
    if sock in outputs:
        outputs.remove(sock)
    inputs.remove(sock)
    # send connection close msg to controller
    upstream.put(scl.addheader('', scl.SCLT_CLOSE))
    return None, -1


def main():
    tcp_client = None
    last_of_seq = -1
    last_link_seq = -1

    while True:
        adjust_outputs(outputs, udp_conn, tcp_client, upstream, downstream)
        rlist, wlist, elist = select.select(inputs, outputs, inputs)

        for r in rlist:
            if r is udp_conn.sock:
                data, addr = r.recvfrom(RECV_BUF_SIZE)
                logger.debug('receive msg from ctrl_scl %s', addr[0])
                if data:
                    type, seq, data = scl.parseheader(data)
                    if type is scl.SCLT_OF and seq > last_of_seq:
                        last_of_seq = seq
                        downstream.put(data)
                    elif type is scl.SCLT_LINK_RQST and seq > last_link_seq:
                        last_link_seq = seq
                        # blocking
                        # TODO: non-blocking
                        ovsdb_conn.send(json.dumps(db_link_state_query))
                        response = ovsdb_conn.recv(RECV_BUF_SIZE)
                        link_state = scl_link_state()
                        msg = link_state.pack(response.port, response.state)
                        upstream.put(scl.addheader(msg, scl.SCLT_LINK_RPLY))

            elif r is tcp_serv.sock:
                logger.info('new connection from the switch')
                tcp_client, addr = r.accept()   # need to set non-blocking ?
                inputs.append(tcp_client)
                outputs.append(tcp_client)
                logger.debug(
                    'send SCLT_HELLO msg to ctrl_scl to '
                    'set up connection between ctrl_scl and controller')
                upstream.put(scl.addheader('', scl.SCLT_HELLO))

            elif r is tcp_client:
                logger.debug('receive msg from switch')
                try:
                    data = r.recv(RECV_BUF_SIZE)
                    if data:
                        # add scl header, put data into upstream
                        handle_of_msg(upstream, data)
                    else:
                        logger.info(
                            'connection to switch closed by the switch')
                        tcp_client, last_of_seq = tcp_close(
                            r, inputs, outputs, upstream)
                except socket.error, e:
                    logger.error(
                        'connection to switch closed abnormally, error %s' % e)
                    tcp_client, last_of_seq = tcp_close(
                        r, inputs, outputs, upstream)

        for w in wlist:
            if w is udp_conn.sock:
                logger.debug('broadcast msg to ctrl_scl')
                next_msg = upstream.get_nowait()
                w.sendto(next_msg, udp_conn.dst_addr)

            elif w is tcp_client:
                logger.debug('send msg to switch')
                next_msg = downstream.get_nowait()
                w.send(next_msg)


if __name__ == "__main__":
    main()
