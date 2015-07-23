#! /usr/bin/python

import Queue
import select
import socket
import errno
import logging
from lib.const import *
from lib.socket_utils import *
from lib.libopenflow_01 import ofp_port_status
import lib.sclprotocol as scl


upstreams = {}      # k: v is conn_id: data_to_be_sent_to_controller
downstreams = {}    # k: v is conn_id: data_to_be_sent_to_sw_scl
last_seqs = {}      # k: v is conn_id: last_sequence_num_in_the_connection

udp_mcast = UdpMcastListener(
    ctrl_scl_mcast_grp, ctrl_scl_mcast_port, ctrl_scl_intf)
udp_mcast.open()
# tcp condition will open when received hello from switch
tcp_conns = TcpConns(ctrl_host, ctrl_port)

inputs = [udp_mcast.sock]
outputs = []

LOG_FILENAME = None
LEVEL = logging.INFO    # DEBUG shows the whole states
logging.basicConfig(
    format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt = '%Y%m%d %H:%M:%S', level = LEVEL, filename = LOG_FILENAME)


def isempty(streams):
    for k in streams:
        if not streams[k].empty():
            return False
    return True


def adjust_outputs(outputs, udp_mcast, tcp_conns, upstreams, downstreams):
    '''
    when stream is empty, remove the corresponding socket from outputs
    if writeable socket is put into outputs directly, select will be called
    more frequentlty and the cpu usage may be 100%.
    '''
    if not isempty(downstreams) and udp_mcast.sock not in outputs:
        outputs.append(udp_mcast.sock)
    elif isempty(downstreams) and udp_mcast.sock in outputs:
        outputs.remove(udp_mcast.sock)

    for conn_id in tcp_conns.id2conn:
        conn = tcp_conns.id2conn[conn_id]
        if conn.connectted:
            if not upstreams[conn_id].empty() and conn.sock not in outputs:
                outputs.append(conn.sock)
            elif upstreams[conn_id].empty() and conn.sock in outputs:
                outputs.remove(conn.sock)


def tcp_close(
        tcp_conns, sock, conn_id, inputs,
        outputs, upstreams, downstreams, last_seqs):
    '''
    clean up the closed tcp condition
    '''
    if sock in outputs:
        outputs.remove(sock)
    if sock in inputs:
        inputs.remove(sock)
    del upstreams[conn_id]
    del downstreams[conn_id]
    del last_seqs[conn_id]
    tcp_conns.close(conn_id)


def handle_of_msg(upstreams, conn_id, data):
    '''
    parse of link state
    put data into upstreams
    '''
    offset = 0
    data_length = len(data)
    logging.debug('data_length: %d' % data_length)
    # parse multiple of msgs in one data
    while data_length - offset >= 8:
        of_type = ord(data[offset + 1])
        msg_length = ord(data[offset + 2]) << 8 | ord(data[offset + 3])
        logging.debug('msg_length: %d' % msg_length)
        if data_length - offset < msg_length:
            break

        if of_type == 12:
            port_status = ofp_port_status()
            port_status.unpack(data[offset: offset + msg_length])
            logging.info(
                '%s %d' % (port_status.desc.name, port_status.desc.state))
            upstreams[conn_id].put(data[offset: offset + msg_length])
        else:
            upstreams[conn_id].put(data[offset: offset + msg_length])

        offset = offset + msg_length


def main():
    while True:
        adjust_outputs(outputs, udp_mcast, tcp_conns, upstreams, downstreams)
        rlist, wlist, elist = select.select(inputs, outputs, inputs)

        for w in wlist:
            if w is udp_mcast.sock:
                # udp_mcast socket is writeable
                for conn_id in tcp_conns.id2conn:
                    if not downstreams[conn_id].empty():
                        logging.debug('send msg to sw_scl %s' % id2str(conn_id))
                        next_msg = downstreams[conn_id].get_nowait()
                        udp_mcast.sendto(next_msg, conn_id)

            elif w in tcp_conns.sock2conn:
                # tcp socket is writeable
                conn = tcp_conns.sock2conn[w]
                if conn.connectted:
                    logging.debug('send msg to controller')
                    next_msg = upstreams[conn.conn_id].get_nowait()
                    conn.send(next_msg)
                else:
                    # check the connecting socket
                    connectted, err = conn.isconnectted()
                    if not connectted:
                        logging.error(
                            'connecting to controller fails, errno %d' % err)
                        tcp_close(
                            tcp_conns, w, conn.conn_id, inputs,
                            outputs, upstreams, downstreams, last_seqs)
                    else:
                        logging.info(
                            'connection to controller successful, '
                            'conn_id: %d' % conn.conn_id)
                        inputs.append(w)

        for r in rlist:
            if r is udp_mcast.sock:
                data, conn_id = udp_mcast.recvfrom(RECV_BUF_SIZE)
                logging.debug('receive msg from sw_scl %s' % id2str(conn_id))
                if data:
                    type, seq, data = scl.parseheader(data)
                    if conn_id in last_seqs:
                        if last_seqs[conn_id] >= seq:
                            logging.warn('receive disordered msg from sw_scl')
                        else:
                            last_seqs[conn_id] = seq
                            if type is scl.SCLT_CLOSE:
                                # close the connection to controller
                                logging.debug('  receive SCLT_CLOSE')
                                conn = tcp_conns.id2conn[conn_id]
                                if conn.connectted:
                                    logging.info(
                                        'the connection to controller '
                                        'is closed by ctrl_scl, '
                                        'conn_id: %d', conn_id)
                                    tcp_close(
                                        tcp_conns, conn.sock, conn.conn_id,
                                        inputs, outputs, upstreams,
                                        downstreams, last_seqs)
                            elif type is scl.SCLT_OF:
                                logging.debug('  receive SCLT_OF')
                                handle_of_msg(upstreams, conn_id, data)
                            else:
                                logging.warn(
                                    'receive wrong SCLT_TYPE %d' % type)

                    elif conn_id not in last_seqs:
                        if type is scl.SCLT_HELLO:
                            logging.debug('  receive SCLT_HELLO')
                            # set up a connection to controller
                            ret, err = tcp_conns.open(conn_id)
                            sock = tcp_conns.id2conn[conn_id].sock
                            # add connecting socket to checking list (outputs)
                            outputs.append(sock)
                            upstreams[conn_id] = Queue.Queue()
                            downstreams[conn_id] = Queue.Queue()
                            last_seqs[conn_id] = seq
                            if ret:
                                logging.info(
                                    'connection to controller successful, '
                                    'conn_id: %d', conn_id)
                                inputs.append(sock)
                            elif err.errno is not errno.EINPROGRESS:
                                logging.error(
                                    'connecting to controller fails, errno %d'
                                    % err.errno)
                        else:
                            logging.warn(
                                'receive wrong type msg (should be SCLT_HELLO)')

            elif r in tcp_conns.sock2conn:
                logging.debug('receive msg from controller')
                conn = tcp_conns.sock2conn[r]
                try:
                    data = conn.recv(RECV_BUF_SIZE)
                    if data:
                        # add scl header to msg, put data into downstreams
                        downstreams[conn.conn_id].put(
                            scl.addheader(data, scl.SCLT_OF))
                    else:
                        logging.info(
                            'connection closed by controller, '
                            'conn_id: %d', conn.conn_id)
                        tcp_close(
                            tcp_conns, r, conn.conn_id, inputs,
                            outputs, upstreams, downstreams, last_seqs)
                except socket.error, e:
                    logging.error('error in connection to controller: %s' % e)


if __name__ == "__main__":
    main()
