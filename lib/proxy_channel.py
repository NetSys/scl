import Queue
import errno
from const import RECV_BUF_SIZE
from socket_utils import *
from gossiper import LinkLog
import scl_protocol as scl


class Streams(object):
    '''
    data received or to be sent
    '''
    def __init__(self, host_id, hosts_num):
        self.upstreams = {}         # conn_id: data_to_be_sent_to_controller
        self.downstreams = {}       # conn_id: data_to_be_sent_to_scl_agent
        self.last_of_seqs = {}      # conn_id: last_connection_sequence_num
        self.link_log = LinkLog(host_id, hosts_num)

    def downstreams_empty(self):
        for k in self.downstreams:
            if not self.downstreams[k].empty():
                return False
        return True

    def open(self, conn_id, of_seq):
        self.upstreams[conn_id] = Queue.Queue()
        self.downstreams[conn_id] = Queue.Queue()
        self.last_of_seqs[conn_id] = of_seq
        self.link_log.open(id2str(conn_id))

    def delete(self, conn_id):
        del self.upstreams[conn_id]
        del self.downstreams[conn_id]
        del self.last_of_seqs[conn_id]
        self.link_log.delete(id2str(conn_id))


class Scl2Ctrl(object):
    '''
    channel from scl to controller, containing multiple connections
    each connection corresponding to a switch connection
    '''
    def __init__(self, ctrl_host, ctrl_port, streams, logger):
        self.tcp_conns = TcpConns(ctrl_host, ctrl_port)
        self.logger = logger
        self.streams = streams
        self.inputs = []
        self.outputs = []

    def open(self, conn_id, seq):
        ret, err = self.tcp_conns.open(conn_id)
        sock = self.tcp_conns.id2conn[conn_id].sock
        # add connecting socket to checking list (outputs)
        self.outputs.append(sock)
        self.streams.open(conn_id, seq)
        if ret:
            self.logger.info(
                'connection to controller successful, conn_id: %d', conn_id)
            self.inputs.append(sock)
        elif err.errno is not errno.EINPROGRESS:
            self.logger.error(
                'connecting to controller fails, errno %d' % err.errno)

    def adjust_outputs(self):
        '''
        when stream is empty, remove the corresponding socket from outputs.
        if writeable socket is put into outputs directly, select will be called
        more frequentlty and the cpu usage may be 100%.
        '''
        for conn_id in self.tcp_conns.id2conn:
            conn = self.tcp_conns.id2conn[conn_id]
            if conn.connectted:
                if not self.streams.upstreams[conn_id].empty()\
                        and conn.sock not in self.outputs:
                    self.outputs.append(conn.sock)
                elif self.streams.upstreams[conn_id].empty()\
                        and conn.sock in self.outputs:
                    self.outputs.remove(conn.sock)

    def clean_connection(self, sock, conn_id):
        '''
        clean up the closed tcp connection
        '''
        if sock in self.outputs:
            self.outputs.remove(sock)
        if sock in self.inputs:
            self.inputs.remove(sock)
        self.streams.delete(conn_id)
        self.tcp_conns.close(conn_id)

    def close_connection(self, conn_id):
        '''
        close the connection with conn_id
        '''
        conn = self.tcp_conns.id2conn[conn_id]
        if conn.connectted:
            self.logger.info(
                'the connection to controller is closed by scl_proxy, '
                'conn_id: %d', conn_id)
            self.clean_connection(conn.sock, conn_id)

    def wait(self, selector):
        self.adjust_outputs()
        selector.wait(self.inputs, self.outputs)

    def run(self, lists):
        for s in self.tcp_conns.sock2conn.keys():
            # socket is writeable
            if s in lists[1]:
                conn = self.tcp_conns.sock2conn[s]
                if conn.connectted:
                    self.logger.debug('send msg to controller')
                    next_msg = self.streams.upstreams[conn.conn_id].get_nowait()
                    conn.send(next_msg)
                # connection is on going or failed
                else:
                    # check the connecting socket
                    connectted, err = conn.isconnectted()
                    if connectted:
                        self.logger.info(
                            'connection to controller successful, '
                            'conn_id: %d' % conn.conn_id)
                        self.inputs.append(s)
                    elif not connectted and err is not errno.EINPROGRESS:
                        self.logger.error(
                            'connecting to controller fails, errno %d' % err)
                        self.clean_connection(s, conn.conn_id)
            # socket is readable
            if s in lists[0]:
                self.logger.debug('receive msg from controller')
                conn = self.tcp_conns.sock2conn[s]
                try:
                    data = conn.recv(RECV_BUF_SIZE)
                    if data:
                        # add scl header to msg, put data into downstreams
                        self.streams.downstreams[conn.conn_id].put(
                            scl.addheader(data, scl.SCLT_OF))
                    else:
                        self.logger.info(
                            'connection closed by controller, '
                            'conn_id: %d', conn.conn_id)
                        self.clean_connection(s, conn.conn_id)
                except socket.error, e:
                    logger.error('error in connection to controller: %s' % e)


class Scl2Scl(object):
    '''
    channel from scl on controller side to scl on switch side
    one udp socket as a multicast listener
    '''
    def __init__(
            self, scl_proxy_mcast_grp, scl_proxy_mcast_port,
            scl_proxy_intf, scl2ctrl, timer, streams, logger):
        self.udp_mcast = UdpMcastListener(
                scl_proxy_mcast_grp, scl_proxy_mcast_port, scl_proxy_intf)
        self.udp_mcast.open()
        self.scl2ctrl = scl2ctrl
        self.timer = timer
        self.streams = streams
        self.logger = logger

    def handle_hello_msg(self, conn_id, seq, data):
        if conn_id in self.streams.last_of_seqs:
            self.logger.warn('receive wrong SCLT_TYPE (SCLT_HELLO)')
        else:
            self.logger.debug('receive SCLT_HELLO')
            # set up a connection from scl to controller
            self.scl2ctrl.open(conn_id, seq)

    def handle_of_msg(self, conn_id, seq, data):
        if conn_id not in self.streams.last_of_seqs:
            self.logger.warn(
                'receive wrong type msg (except SCLT_HELLO)')
        else:
            if self.streams.last_of_seqs[conn_id] >= seq:
                self.logger.warn('receive disordered msg from scl_agent')
            else:
                self.streams.last_of_seqs[conn_id] = seq
                self.logger.debug('receive SCLT_OF')
                self.streams.upstreams[conn_id].put(data)

    def handle_close_msg(self, conn_id, seq, data):
        if conn_id not in self.streams.last_of_seqs:
            self.logger.warn(
                'receive wrong type msg (except SCLT_HELLO)')
        else:
            if self.streams.last_of_seqs[conn_id] >= seq:
                self.logger.warn('receive disordered msg from scl_agent')
            else:
                # close the connection from scl to controller
                self.streams.last_of_seqs[conn_id] = seq
                self.logger.debug('receive SCLT_CLOSE')
                self.scl2ctrl.close_connection(conn_id)

    def handle_link_notify_msg(self, conn_id, seq, data):
        switch = id2str(conn_id)
        if switch not in self.streams.link_log.switches():
            self.logger.warn(
                'receive wrong type msg (except SCLT_HELLO)')
        else:
            # parse scl link state msg
            port, state, version = scl.link_state_unpack(data)
            self.streams.link_log.update(switch, port, version, state)
            self.logger.info(
                    '%s, %s, version: %d, state: %s' % (
                        switch, port, version,
                        'up' if state == 0 else 'down'))

    def process_data(self, conn_id, type, seq, data):
        '''
        process data received from scl_agent
        classify type, check sequence num, msg enqueue
        '''
        if type is scl.SCLT_OF:
            self.handle_of_msg(conn_id, seq, data)
        elif type is scl.SCLT_HELLO:
            self.handle_hello_msg(conn_id, seq, data)
        elif type is scl.SCLT_CLOSE:
            self.handle_close_msg(conn_id, seq, data)
        elif type is scl.SCLT_LINK_NOTIFY:
            self.handle_link_notify_msg(conn_id, seq, data)

    def wait(self, selector):
        if not self.streams.downstreams_empty():
            selector.wait([self.udp_mcast.sock], [self.udp_mcast.sock])
        else:
            selector.wait([self.udp_mcast.sock], [])

    def run(self, lists):
        # socket is writeable
        if self.udp_mcast.sock in lists[1]:
            for conn_id in self.streams.downstreams:
                if not self.streams.downstreams[conn_id].empty():
                    self.logger.debug(
                        'send msg to scl_agent %s' % id2str(conn_id))
                    next_msg = self.streams.downstreams[conn_id].get_nowait()
                    self.udp_mcast.sendto(next_msg, conn_id)

        # socket is readable
        if self.udp_mcast.sock in lists[0]:
            data, conn_id = self.udp_mcast.recvfrom(RECV_BUF_SIZE)
            self.logger.debug('receive msg from scl_agent %s' % id2str(conn_id))
            if data:
                type, seq, data = scl.parseheader(data)
                self.process_data(conn_id, type, seq, data)

        # check timer
        # (count + 1) % 3 per second
        # send link state request each three seconds
        if self.timer.time_up and self.timer.count == 1:
            self.logger.debug('periodically send rqst msg')
            for conn_id in self.streams.downstreams:
                self.logger.debug(
                        'send link state request msg to scl_agent '
                        '%s' % id2str(conn_id))
                self.udp_mcast.sendto(
                        scl.addheader('', scl.SCLT_LINK_RQST), conn_id)
