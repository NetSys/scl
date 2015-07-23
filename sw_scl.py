#! /usr/bin/python

import Queue
import select
import logging
from lib.const import *
from lib.socket_utils import *
import lib.sclprotocol as scl


upstream = Queue.Queue()
downstream = Queue.Queue()

udp_conn = UdpConn(ctrl_scl_mcast_grp, ctrl_scl_mcast_port)
udp_conn.open()

tcp_serv = TcpListen(sw_scl_serv_host, sw_scl_serv_port)
tcp_serv.open()

inputs = [udp_conn.sock, tcp_serv.sock]
outputs = [udp_conn.sock]

LOG_FILENAME = None
LEVEL = logging.INFO    # DEBUG shows the whole states
logging.basicConfig(
    format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt = '%Y%m%d %H:%M:%S', level = LEVEL, filename = LOG_FILENAME)


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

def tcp_close(sock, inputs, outputs, upstream):
    if sock in outputs:
        outputs.remove(sock)
    inputs.remove(sock)
    # send connection close msg to controller
    upstream.put(scl.addheader('', scl.SCLT_CLOSE))
    return None, -1

def main():
    tcp_client = None
    last_seq = -1

    while True:
        adjust_outputs(outputs, udp_conn, tcp_client, upstream, downstream)
        rlist, wlist, elist = select.select(inputs, outputs, inputs)

        for r in rlist:
            if r is udp_conn.sock:
                data, addr = r.recvfrom(RECV_BUF_SIZE)
                logging.debug('receive msg from ctrl_scl %s', addr[0])
                if data:
                    type, seq, data = scl.parseheader(data)
                    if type is scl.SCLT_OF and seq > last_seq:
                        last_seq = seq
                        downstream.put(data)

            elif r is tcp_serv.sock:
                logging.info('new connection from the switch')
                tcp_client, addr = r.accept()   # need to set non-blocking ?
                inputs.append(tcp_client)
                outputs.append(tcp_client)
                logging.debug(
                    'send SCLT_HELLO msg to ctrl_scl to '
                    'set up connection between ctrl_scl and controller')
                upstream.put(scl.addheader('', scl.SCLT_HELLO))

            elif r is tcp_client:
                logging.debug('receive msg from switch')
                try:
                    data = r.recv(RECV_BUF_SIZE)
                    if data:
                        # add scl header, put data into upstreams
                        upstream.put(scl.addheader(data, scl.SCLT_OF))
                    else:
                        logging.info(
                            'connection to switch closed by the switch')
                        tcp_client, last_seq = tcp_close(
                            r, inputs, outputs, upstream)
                except socket.error, e:
                    logging.error(
                        'connection to switch closed abnormally, error %s' % e)
                    tcp_client, last_seq = tcp_close(
                        r, inputs, outputs, upstream)

        for w in wlist:
            if w is udp_conn.sock:
                logging.debug('broadcast msg to ctrl_scl')
                next_msg = upstream.get_nowait()
                w.sendto(next_msg, udp_conn.dst_addr)

            elif w is tcp_client:
                logging.debug('send msg to switch')
                next_msg = downstream.get_nowait()
                w.send(next_msg)


if __name__ == "__main__":
    main()
