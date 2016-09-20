import Queue
import errno
import json
from conf.const import RECV_BUF_SIZE, TE_VENDOR
from socket_utils import *
import libopenflow_01 as of
import scl_protocol as scl


ECHO_TIMEOUT = 10

# some functions from pox controller
# pox/pox/openflow/util.py
# pox/pox/openflow/of_01.py
#----------------------------------------------------------------------------#
def make_type_to_unpacker_table():
    """
    Returns a list of unpack methods.

    The resulting list maps OpenFlow types to functions which unpack
    data for those types into message objects.
    """
    top = max(of._message_type_to_class)
    r = [of._message_type_to_class[i].unpack_new for i in range(0, top)]
    return r

unpackers = make_type_to_unpacker_table()

def handle_HELLO(scl, conn, msg):
    scl.logger.debug('ofp_handshake: hello received')
    hello = of.ofp_hello()
    scl.streams.upstreams[conn.conn_id].put(hello.pack())

def handle_ECHO_REPLY(scl, conn, msg):
    if scl.streams.ofp_echo_ids[conn.conn_id] != msg.xid:
        scl.logger.error(
            'echo err: the connection to controller is closed by scl_proxy, '
            'echo_rqst_xid: %d, while echo_rply_xid: %d, conn_id: %d' % (
                scl.streams.ofp_echo_ids[conn.conn_id], msg.xid, conn.conn_id))
        scl.clean_connection(conn.conn_id, conn.sock)
    else:
        scl.logger.debug('conn_id: %d, ofp_echo_reply received' % conn.conn_id)
        scl.streams.ofp_echo_times[conn.conn_id] = 0

def handle_ECHO_REQUEST(scl, conn, msg):
    reply = msg
    reply.header_type = of.OFPT_ECHO_REPLY
    scl.streams.upstreams[conn.conn_id].put(reply.pack())

def handle_FEATURES_REQUEST(scl, conn, msg):
    scl.logger.debug('ofp_handshake: features_request received')
    reply = of.ofp_features_reply()
    reply.xid = msg.xid
    reply.datapath_id = scl.streams.agent_list.index(id2str(conn.conn_id))
    scl.streams.upstreams[conn.conn_id].put(reply.pack())

def handle_SET_CONFIG(scl, conn, msg):
    pass

def handle_FLOW_MOD(scl2ctrl, conn, msg):
    if scl2ctrl.streams.ofp_connected[conn.conn_id]:
        # put msg and corresponding scl header into downstreams
        scl2ctrl.streams.downstreams[conn.conn_id].put([msg.pack(), scl.SCLT_OF_PROXY])
        # maintain the whole dataplane flow tables
        scl2ctrl.streams.flow_table_db.ofp_msg_update(conn.conn_id, msg)

def handle_BARRIER_REQUEST(scl, conn, msg):
    reply = msg
    reply.header_type = of.OFPT_BARRIER_REPLY
    scl.streams.upstreams[conn.conn_id].put(reply.pack())
    scl.logger.debug('ofp_handshake: barrier_requset received')
    scl.logger.debug('ofp_handshake: successful')
    scl.streams.ofp_connected[conn.conn_id] = True
    # transfer temp data from handshake_queues to upstreams
    while not scl.streams.handshake_queues[conn.conn_id].empty():
        data = scl.streams.handshake_queues[conn.conn_id].get()
        scl.streams.upstreams[conn.conn_id].put(data)


# A list, where the index is an OFPT, and the value is a function to
# call for that type
# This is generated automatically based on handlerMap
handlers = []

# Message handlers
handlerMap = {
    of.OFPT_HELLO : handle_HELLO,
    of.OFPT_ECHO_REQUEST : handle_ECHO_REQUEST,
    of.OFPT_ECHO_REPLY : handle_ECHO_REPLY,
    of.OFPT_FEATURES_REQUEST : handle_FEATURES_REQUEST,
    of.OFPT_SET_CONFIG : handle_SET_CONFIG,
    of.OFPT_FLOW_MOD : handle_FLOW_MOD,
    of.OFPT_BARRIER_REQUEST : handle_BARRIER_REQUEST,
}

def _set_handlers ():
    handlers.extend([None] * (1 + sorted(handlerMap.keys(),reverse=True)[0]))
    for h in handlerMap:
        handlers[h] = handlerMap[h]


#----------------------------------------------------------------------------#
class LinkLog(object):
    def __init__(self, hosts_num):
        self.log = {}
        self.last_events = {}
        self.peer_num = int(hosts_num) - 1     # not self

    def switches(self):
        return self.log.keys()

    def links(self, switch):
        return self.log[switch].keys()

    def open(self, switch):
        '''
        maybe useless, update method will create the switch key
        '''
        if switch not in self.log:
            self.log[switch] = {}
            self.last_events[switch] = {}

    def delete(self, switch):
        if switch in self.log:
            del self.log[switch]

    def update(self, switch, link, event, state, peer=None):
        upcall_link_status = False
        if switch not in self.log:
            self.log[switch] = {}
            self.last_events[switch] = {}
        if link not in self.log[switch]:
            self.log[switch][link] = {}
            self.last_events[switch][link] = -1
        if event not in self.log[switch][link]:
            if event > self.last_events[switch][link]:
                self.last_events[switch][link] = event
                upcall_link_status = True
            self.log[switch][link][event] = {}
            self.log[switch][link][event]['state'] = state
            self.log[switch][link][event]['peers'] = {}
        if peer is not None:
            self.log[switch][link][event]['peers'][peer] = True
        return (switch, link, state) if upcall_link_status else None

    def digest(self):
        '''
        calculate summary of log to be sent
        '''
        digest = {}
        for switch in self.log:
            digest[switch] = {}
            for link in self.log[switch]:
                digest[switch][link] = []
                last_event = None
                events = sorted(self.log[switch][link].keys())
                for e in events:
                    if last_event is None:
                        digest[switch][link].append(e)
                    elif e - last_event > 1:
                        digest[switch][link].append((last_event, e))
                    elif e == events[-1]:
                        digest[switch][link].append(e)
                    last_event = e
        return digest

    def subtract_events(self, switch, link, events):
        ret = {}
        self_events = sorted(self.log[switch][link].keys())
        # TODO: refine code
        for e in events:
            if e is events[0]:
                for self_e in self_events:
                    if e > self_e:
                        ret[self_e] = self.log[switch][link][self_e]
            if e is events[-1]:
                for self_e in self_events:
                    if e < self_e:
                        ret[self_e] = self.log[switch][link][self_e]
            if e is not events[0] and e is not events[-1]:
                for self_e in self_events:
                    if e[0] < self_e and e[1] > self_e:
                        ret[self_e] = self.log[switch][link][self_e]
        return ret

    def subtract_log(self, digest):
        delta = {}
        for switch in self.log:
            if switch not in digest:
                delta[switch] = self.log[switch]
            else:
                delta[switch] = {}
                for link in self.log[switch]:
                    if link not in digest[switch]:
                        delta[switch][link] = self.log[switch][link]
                    else:
                        delta[switch][link] = self.subtract_events(
                                switch, link, digest[switch][link])
                        if not delta[switch][link]:
                            del delta[switch][link]
                if not delta[switch]:
                    del delta[switch]
        return delta

    def truncate(self):
        '''
        truncate tail, if all messages have been seen by each others
        '''
        # TODO: how can host know that others have received its message?
        for switch in self.log:
            for link in self.log[switch]:
                events = sorted(self.log[switch][link].keys())
                for e in events:
                    if len(self.log[switch][link][e]['peers'].keys()) is self.peer_num:
                        del self.log[switch][link][e]   # or write it to disk
                    else:
                        break
#----------------------------------------------------------------------------#


class Streams(object):
    '''
    data received or to be sent
    '''
    def __init__(self, hosts_num, logger):
        self.upstreams = {}         # conn_id: data_to_be_sent_to_controller
        self.downstreams = {}       # conn_id: data_to_be_sent_to_scl_agent [msg, type]
        self.handshake_queues = {}  # temp switch msgs while proxy handshaking with ctrls
        self.ofp_buffs = {}         # buffer uncomplete ctrls ofp msgs read from sockets
        self.ofp_connected = {}
        self.ofp_echo_times = {}
        self.ofp_echo_ids = {}
        self.link_log = LinkLog(hosts_num)
        self.flow_table_db = scl.FlowTableDB(logger)
        self.flow_stats_db = scl.FlowStatsDB(logger)
        self.flow_stats_buff = {}
        self.agent_list = []

    def downstreams_empty(self):
        for k in self.downstreams:
            if not self.downstreams[k].empty():
                return False
        return True

    def downstreams_enqueue(self, con, msgs):
        for msg in msgs:
            self.downstreams[con].put(msg)

    def upcall_link_status(self, switch, link, state):
        port_status = of.ofp_port_status()
        port_status.reason = of.OFPPR_MODIFY
        port_name, port_no = link.split(':')
        port_status.desc.port_no = int(port_no)
        port_status.desc.name = port_name
        port_status.desc.state = state
        if self.ofp_connected[str2id(switch)]:
            self.upstreams[str2id(switch)].put(port_status.pack())
        else:
            self.handshake_queues[str2id(switch)].put(port_status.pack())

    def upcall_traffic_matrices(self, traffic_matrices):
        # use OFPST_VENDOR packet to send traffic_matrices data
        flow_stats = of.ofp_stats_reply()
        flow_stats.type = of.OFPST_VENDOR
        flow_stats.body = of.ofp_vendor_stats_generic()
        flow_stats.body.vendor = TE_VENDOR
        flow_stats.body.data = json.dumps(traffic_matrices)
        # send traffic_matrices data use any sw connection
        self.upstreams[str2id(traffic_matrices.keys()[0])].put(flow_stats.pack())

    def open(self, conn_id):
        self.upstreams[conn_id] = Queue.Queue()
        self.downstreams[conn_id] = Queue.Queue()
        self.handshake_queues[conn_id] = Queue.Queue()
        self.ofp_buffs[conn_id] = ''
        self.ofp_connected[conn_id] = False
        self.ofp_echo_ids[conn_id] = 0
        self.ofp_echo_times[conn_id] = 0
        self.link_log.open(id2str(conn_id))
        self.flow_table_db.open(conn_id)
        self.flow_stats_db.open(conn_id)
        self.flow_stats_buff[conn_id] = []

    def delete(self, conn_id):
        del self.upstreams[conn_id]
        del self.downstreams[conn_id]
        del self.handshake_queues[conn_id]
        del self.ofp_buffs[conn_id]
        del self.ofp_connected[conn_id]
        del self.ofp_echo_ids[conn_id]
        del self.ofp_echo_times[conn_id]
        self.link_log.delete(id2str(conn_id))
        self.flow_table_db.delete(conn_id)
        self.flow_stats_db.delete(conn_id)
        del self.flow_stats_buff[conn_id]


class Scl2Ctrl(object):
    '''
    channel from scl to controller, containing multiple connections
    each connection corresponding to a switch connection
    '''
    def __init__(self, ctrl_host, ctrl_port, timer, streams, logger):
        self.tcp_conns = TcpConnsMulti2One(ctrl_host, ctrl_port)
        self.logger = logger
        self.streams = streams
        self.timer = timer
        self.inputs = []
        self.outputs = []
        _set_handlers()

    def open(self, conn_id):
        ret, err = self.tcp_conns.open(conn_id)
        sock = self.tcp_conns.id2conn[conn_id].sock
        # add connecting socket to checking list (outputs)
        self.outputs.append(sock)
        self.streams.open(conn_id)
        if ret:
            self.logger.info(
                'connection to controller successful, conn_id: %d', conn_id)
            self.inputs.append(sock)
        elif err.errno is not errno.EINPROGRESS:
            self.logger.error(
                'connecting to controller fails, errno %d' % err.errno)
            self.outputs.remove(sock)
            self.tcp_conns.close(conn_id)

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

    def clean_connection(self, conn_id, sock=None):
        # clean up the closed tcp connection
        self.logger.debug("scl2ctrl clean_connection: %s" % id2str(conn_id))
        if sock is None:
            sock = self.tcp_conns.id2conn[conn_id].sock
        if sock in self.outputs:
            self.outputs.remove(sock)
        if sock in self.inputs:
            self.inputs.remove(sock)
        self.streams.delete(conn_id)
        self.tcp_conns.close(conn_id)

    def handle_of_msg(self, conn, data):
        '''
        parse of openflow messages
        put data into downstream
        '''
        offset = 0
        data_length = len(data)
        tmp_buff = self.streams.ofp_buffs[conn.conn_id]
        tmp_buff += data
        buff_length = len(tmp_buff)
        self.logger.debug(
                'data_length: %d, buff_length: %d.' % (data_length, buff_length))
        # parse multiple msgs in buff
        while buff_length - offset >= 8:
            ofp_type = ord(tmp_buff[offset + 1])

            # ofp msg length checking
            # assume that 2nd and 3rd bytes are for length
            msg_length = ord(tmp_buff[offset + 2]) << 8 | ord(tmp_buff[offset + 3])
            if buff_length - offset < msg_length:
                break

            # ofp version checking
            if ord(tmp_buff[offset]) != of.OFP_VERSION:
                if ofp_type == of.OFPT_HELLO:
                    self.logger.info(
                        'ofp ver err: the connection to controller is closed by scl_proxy, '
                        'conn_id: %d' % conn.conn_id)
                    self.clean_connection(conn.conn_id, conn.sock)
                else:
                    self.logger.warn(
                            'Bad OpenFlow version (0x%02x)' % ord(tmp_buff[offset]))
                    offset = offset + msg_length
                    continue

            self.logger.debug('ofp_type: %d, msg_length: %d' % (ofp_type, msg_length))

            # unpack msg according to ofp_type
            new_offset, msg = unpackers[ofp_type](tmp_buff, offset)
            assert new_offset - offset == msg_length
            offset = new_offset

            # handle ofp msg
            try:
                h = handlers[ofp_type]
                h(self, conn, msg)
            except Exception, e:
                self.logger.error(
                        "Exception while handling OpenFlow %s msg, err: %s" % (ofp_type, e))

        # save the uncomplete buffer
        self.streams.ofp_buffs[conn.conn_id] = tmp_buff[offset:]

    def wait(self, selector):
        self.adjust_outputs()
        selector.wait(self.inputs, self.outputs)

    def run(self, lists):
        for s in self.tcp_conns.sock2conn.keys():
            # socket is writeable
            if s in lists[1]:
                conn = self.tcp_conns.sock2conn[s]
                # connection socket is up
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
                        # wait the controller to send ofp_hello msg first
                        # start of channel passively
                        self.inputs.append(s)
                    elif not connectted and err is not errno.EINPROGRESS:
                        self.logger.error(
                            'connecting to controller fails, errno %d' % err)
                        self.clean_connection(conn.conn_id, s)
            # socket is readable
            if s in lists[0]:
                self.logger.debug('receive msg from controller')
                conn = self.tcp_conns.sock2conn[s]
                try:
                    data = conn.recv(RECV_BUF_SIZE)
                    if data:
                        self.handle_of_msg(conn, data)
                    else:
                        self.logger.info(
                            'connection closed by controller, conn_id: %d' % conn.conn_id)
                        self.clean_connection(conn.conn_id, s)
                except socket.error, e:
                    self.logger.error('error in connection to controller: %s' % e)
                    self.clean_connection(conn.conn_id, s)
            # check timer, time up per second
            # send echo request to controller every second
            if self.timer.time_up:
                conn = self.tcp_conns.sock2conn[s]
                if conn.connectted and self.streams.ofp_connected[conn.conn_id]:
                    self.logger.debug('periodically send ofp_echo_request msg')
                    if self.streams.ofp_echo_times[conn.conn_id] >= ECHO_TIMEOUT:
                        self.logger.error(
                            'echo timeout: the connection to controller is closed by scl_proxy, '
                            'conn_id: %d' % conn.conn_id)
                        self.clean_connection(conn.conn_id, conn.sock)
                    else:
                        echo_rqst = of.ofp_echo_request()
                        # FIXME: may receive disordered xid, temp method: set xid 0
                        echo_rqst.xid = 0
                        conn.send(echo_rqst.pack())
                        self.streams.ofp_echo_ids[conn.conn_id] = echo_rqst.xid
                        self.streams.ofp_echo_times[conn.conn_id] += 1


class Scl2Scl(object):
    '''
    base channel from scl on controller side to scl on switch side
    '''
    def __init__(self, scl2ctrl, timer, streams, logger, proxy_list, agent_list, scl_proxy_intf, fstats):
        self.scl2ctrl = scl2ctrl
        self.timer = timer
        self.streams = streams
        self.logger = logger
        self.proxy_list = proxy_list
        self.agent_list = agent_list
        self.streams.agent_list = agent_list    # map name to id
        self.addr = scl_proxy_intf
        scl.my_addr = scl_proxy_intf
        scl.my_type = scl.SCL_PROXY
        self.fstats = fstats

    def handle_of_msg(self, conn_id, msg):
        self.logger.debug('receive SCLT_OF msg')
        self.streams.upstreams[conn_id].put(msg)

    def handle_link_notify_msg(self, conn_id, msg):
        # parse scl link state msg
        switch = id2str(conn_id)
        link, port_no, state, version = scl.link_state_unpack(msg)
        link = str(link) + ':' + str(port_no)
        ret = self.streams.link_log.update(switch, link, version, state)
        if ret:
            self.streams.upcall_link_status(ret[0], ret[1], ret[2])
        self.logger.info(
                '%s, %s, version: %d, state: %s' % (
                    switch, link, version, state))

    def handle_flow_table_notify_msg(self, conn_id, msg):
        version, host1, host2, outport = scl.flow_entry_unpack(msg)
        self.streams.flow_table_db.sw_notify_update(
                conn_id, version, host1, host2, outport)

    def handle_flow_stats_reply_msg(self, conn_id, msg):
        addr_id, seq, sec, nsec, raw_ofp_stats_rply_msg = scl.flow_stats_rply_unpack(msg)
        # not for us
        if addr_id != self.addr:
            return

        # assemble ofp stats reply msgs
        ofp_stats_rply_msg = scl.parse_ofp_flow_stats_reply_msg(raw_ofp_stats_rply_msg)
        if len(self.streams.flow_stats_buff[conn_id]) != 0:
            if ofp_stats_rply_msg.xid == self.streams.flow_stats_buff[conn_id][0].xid:
                self.streams.flow_stats_buff[conn_id].append(ofp_stats_rply_msg)
            else:
                self.logger.error(
                        'continuous stats failed new xid %d, excepted xid %d' % (
                            ofp_stats_rply_msg.xid,
                            self.streams.flow_stats_buff[conn_id][0].xid))
        else:
            self.streams.flow_stats_buff[conn_id] = [ofp_stats_rply_msg]

        if ofp_stats_rply_msg.is_last_reply:
            msgs = []
            for msg in self.streams.flow_stats_buff[conn_id]:
                msgs.extend(msg.body)
            self.streams.flow_stats_buff[conn_id] = []
            # update complete reply msgs
            timestamp = sec + nsec / float(1000000000)
            self.streams.flow_stats_db.update(conn_id, seq, timestamp, msgs)

    def handle_gossip_syn_msg(self, conn_id, msg):
        '''
               **gossip pull method**
        |---       syn, digest        -->|
        |                                |
        |<-- ack, response of missing ---|
        '''
        digest = byteify(json.loads(msg))
        self.logger.debug(
                "receive syn from %s, digest: %s" % (
                    id2str(conn_id), json.dumps(digest)))
        delta = self.streams.link_log.subtract_log(digest)
        if delta:
            self.logger.debug("flood delta: %s" % json.dumps(delta))
            self.send_raw(json.dumps(delta), scl.SCLT_GOSSIP_ACK, scl.ALL_CTRL_ADDR)

    def handle_gossip_ack_msg(self, conn_id, msg):
        delta = byteify(json.loads(msg))
        addr = id2str(conn_id)
        self.logger.debug(
                "receive ack from %s, delta: %s" % (
                    addr, json.dumps(delta)))
        for switch in delta:
            for link in delta[switch]:
                for event, items in delta[switch][link].iteritems():
                    event = int(event)
                    if switch not in self.streams.link_log.switches():
                        self.logger.info(
                                'receive link msg of a new switch by gossiper, '
                                'set up a new connection from proxy to controller')
                        self.scl2ctrl.open(str2id(switch))
                    ret = self.streams.link_log.update(
                            switch, link, event, items['state'], addr)
                    if ret:
                        self.streams.upcall_link_status(ret[0], ret[1], ret[2])
                    for peer in items['peers']:
                        self.streams.link_log.update(switch, link, event, items['state'], peer)

    def process_msg(self, conn_id, sclt, msg):
        # process msg received from scl_agent
        # check seq num, classify type, process msg
        if sclt is scl.SCLT_OF_AGENT:
            self.handle_of_msg(conn_id, msg)
        elif sclt is scl.SCLT_LINK_NOTIFY:
            self.handle_link_notify_msg(conn_id, msg)
        elif sclt is scl.SCLT_FLOW_TABLE_NOTIFY:
            self.handle_flow_table_notify_msg(conn_id, msg)
        elif sclt is scl.SCLT_FLOW_STATS_REPLY:
            self.handle_flow_stats_reply_msg(conn_id, msg)
        elif sclt is scl.SCLT_GOSSIP_SYN:
            self.handle_gossip_syn_msg(conn_id, msg)
        elif sclt is scl.SCLT_GOSSIP_ACK:
            self.handle_gossip_ack_msg(conn_id, msg)

    def send_raw(self, msg, sclt, dst_addr):
        return

    def link_state_rqst(self):
        # check timer, send link state request every three seconds
        if self.timer.time_up and self.timer.link_state_rqst_count == 1:
            ## switches upcall periodically
            # pass
            self.logger.debug('periodically broadcast link state rqst msg')
            # we do not send None msg
            self.send_raw('0', scl.SCLT_LINK_RQST, scl.ALL_SW_ADDR)

    def flow_table_rqst(self):
        # check timer, send flow table request every five seconds
        if self.timer.time_up and self.timer.flow_table_rqst_count == 1:
            ## switches upcall periodically
            # pass
            self.logger.debug('periodically broadcast flow table rqst msg')
            # we do not send None msg
            self.send_raw('0', scl.SCLT_FLOW_TABLE_RQST, scl.ALL_SW_ADDR)

    def flow_table_diff_check(self):
        # check if flow tables between sw and ctrl are different
        # if so, update ofp_flow_mod msgs
        if self.timer.time_up and self.timer.flow_table_rqst_count == 3:
            self.logger.debug('current flow tables status:\n%s' % (
                self.streams.flow_table_db.show()))
            for conn_id, msgs in self.streams.flow_table_db.flow_tables_diff().iteritems():
                if msgs:
                    self.logger.debug('update flow_mod msg to ensure consistency:'
                            '   %d flow entries of %s' % (len(msgs), id2str(conn_id)))
                for msg in msgs:
                    self.send_raw(msg.pack(), scl.SCLT_OF_PROXY, id2str(conn_id))

    def flow_stats_rqst(self):
        # check timer, send flow stats probe request every two seconds
        if self.timer.time_up and self.timer.flow_stats_rqst_count == 1:
            self.logger.debug('periodically broadcast flow stats rqst msg')
            self.send_raw(self.streams.flow_stats_db.create_scl_flow_stats_rqst(self.addr), scl.SCLT_FLOW_STATS_RQST, scl.ALL_SW_ADDR)

    def te_routing_trigger(self):
        # check timer, try to generate te routing
        # according to the traffic matrices every thirty seconds
        if self.timer.time_up and self.timer.try_te_count == 1:
            self.logger.debug('periodically check flow stats')
            traffic_matrices = self.streams.flow_stats_db.check_tm()
            if traffic_matrices:
                self.logger.debug('upcall_traffic_matrices')
                self.streams.upcall_traffic_matrices(traffic_matrices)

    def gossip_syn(self):
        # check timer, time up every two seconds
        if self.timer.time_up and self.timer.gossip_syn_count == 1:
            self.logger.debug(
                    "periodically broadcast gossip syn, digest: %s" % (
                        json.dumps(self.streams.link_log.digest())))
            self.send_raw(json.dumps(self.streams.link_log.digest()), scl.SCLT_GOSSIP_SYN, scl.ALL_CTRL_ADDR)

class Scl2SclUdp(Scl2Scl):
    '''
    channel from scl on controller side to scl on switch side
    one udp socket as a multicast listener
    '''
    def __init__(
            self, scl2ctrl, timer, streams, logger, proxy_list, agent_list,
            scl_proxy_intf, fstats, scl_proxy_port, scl_agent_port):

        super(Scl2SclUdp, self).__init__(scl2ctrl, timer, streams, logger, proxy_list, agent_list, scl_proxy_intf, fstats)
        self.udp_flood = UdpFloodListener('', scl_proxy_port, scl_agent_port)

    def send_raw(self, msg, sclt, dst_addr):
        self.udp_flood.send(scl.scl_udp_pack(msg, sclt, self.addr, dst_addr))

    def wait(self, selector):
        if not self.streams.downstreams_empty():
            selector.wait([self.udp_flood.sock], [self.udp_flood.sock])
        else:
            selector.wait([self.udp_flood.sock], [])

    def run(self, lists):
        # socket is writeable
        if self.udp_flood.sock in lists[1]:
            for conn_id in self.streams.downstreams:
                if not self.streams.downstreams[conn_id].empty():
                    self.logger.debug(
                        'send a msg to scl_agent %s' % id2str(conn_id))
                    msg, sclt = self.streams.downstreams[conn_id].get_nowait()
                    self.send_raw(msg, sclt, id2str(conn_id))

        # socket is readable
        if self.udp_flood.sock in lists[0]:
            data = self.udp_flood.recv(RECV_BUF_SIZE)
            if data:
                pad, sclt, conn_id, msg = scl.scl_udp_unpack(data)
                if msg:
                    self.logger.debug(
                            'receive msgs from %s, type: %d' % (
                                id2str(conn_id), sclt))
                    if id2str(conn_id) in self.agent_list and \
                            id2str(conn_id) not in self.streams.link_log.switches():
                        self.logger.info(
                                'receive msg of a new switch by scl_agent, '
                                'set up a new connection from proxy to controller')
                        self.scl2ctrl.open(conn_id)
                    self.process_msg(conn_id, sclt, msg)

        # periodically
        self.link_state_rqst()
        self.flow_table_rqst()
        self.flow_table_diff_check()
        if self.fstats:
            self.flow_stats_rqst()
            self.te_routing_trigger()
        self.gossip_syn()


class Scl2SclTcp(Scl2Scl):
    '''
    channel from scl on controller side to scl on switch side
    one tcp socket as a listener
    '''
    def __init__(
            self, scl2ctrl, timer, streams, logger, proxy_list, agent_list,
            scl_proxy_intf, fstats, scl_proxy_port):
        super(Scl2SclTcp, self).__init__(scl2ctrl, timer, streams, logger, proxy_list, agent_list, scl_proxy_intf, fstats)
        self.tcp_srvr = TcpListener(scl_proxy_intf, scl_proxy_port)     # connections from other ctrls and sws
        self.tcp_conns = TcpConnsOne2Multi(proxy_list, scl_proxy_port)  # connections to other ctrls
        self.dst_intfs = proxy_list
        self.dst_intfs.remove(self.addr)
        self.inputs = [self.tcp_srvr.sock]
        self.outputs = []
        self.outputs_sw = []
        self.outputs_ctrl = []
        self.waitings = []
        for intf in self.dst_intfs:
            self.open(intf)

    def open(self, intf):
        ret, err = self.tcp_conns.open(intf)
        if ret:
            self.logger.info(
                'successfully connect to scl_proxy, dst: %s' % intf)
            self.outputs_ctrl.append(self.tcp_conns.intf2conn[intf].sock)
        elif err.errno is errno.EINPROGRESS:
            self.logger.info(
                'connecting to scl_proxy, dst: %s' % intf)
            self.waitings.append(self.tcp_conns.intf2conn[intf].sock)
        else:
            self.logger.error(
                    'connect to scl_proxy fails, errno %d, dst: %s' % (
                        err.errno, intf))
            self.tcp_conns.close(intf)

    def adjust_outputs(self):
        for sock in self.outputs_sw:
            conn_id = self.tcp_srvr.sock2conn[sock].conn_id
            if not self.streams.downstreams[conn_id].empty()\
                    and sock not in self.outputs:
                self.outputs.append(sock)
            elif self.streams.downstreams[conn_id].empty()\
                    and sock in self.outputs:
                self.outputs.remove(sock)

    def clean_outcome_connection(self, intf=None, sock=None):
        if not intf and not sock:
            return
        elif not intf:
            intf = self.tcp_conns.sock2conn[sock].conn_id
        elif not sock:
            sock = self.tcp_conns.intf2conn[intf].sock
        self.logger.debug("scl2scltcp clean_outcome_connection: %s" % intf)
        if sock in self.outputs_ctrl:
            self.outputs_ctrl.remove(sock)
        if sock in self.waitings:
            self.waitings.remove(sock)
        self.tcp_conns.close(intf)

    def clean_income_connection(self, conn_id, sock):
        # clean up the closed tcp connections from others
        self.logger.debug("scl2scltcp clean_income_connection: %s" % id2str(conn_id))
        if sock in self.outputs_sw:
            self.outputs_sw.remove(sock)
        if sock in self.outputs:
            self.outputs.remove(sock)
        if sock in self.inputs:
            self.inputs.remove(sock)
        self.tcp_srvr.close(conn_id)
        scl.scl_tcp_close(conn_id)

    def send_raw_to_one(self, conn, msg, sclt, dst_addr):
        try:
            conn.sock.send(scl.scl_tcp_pack(msg, sclt, self.addr, dst_addr))
        except socket.error, e:
            intf = id2str(conn.conn_id) \
                    if isinstance(conn.conn_id, int) else conn.conn_id
            self.logger.error('error in connection to %s, e %s' % (intf, e))
            # TODO: change the conditional statement
            if isinstance(conn.conn_id, int):
                self.clean_income_connection(conn.conn_id, conn.sock)
            else:
                self.clean_outcome_connection(conn.conn_id, conn.sock)

    def send_raw(self, msg, sclt, dst_addr):
        if dst_addr is scl.ALL_CTRL_ADDR:
            for s in self.outputs_ctrl:
                conn = self.tcp_conns.sock2conn[s]
                self.send_raw_to_one(conn, msg, sclt, dst_addr)
            return
        for s in self.outputs_sw:
            conn = self.tcp_srvr.sock2conn[s]
            self.send_raw_to_one(conn, msg, sclt, dst_addr)

    def wait(self, selector):
        self.adjust_outputs()
        selector.wait(self.inputs, self.outputs + self.waitings)

    def run(self, lists):
        # check the connecting socket
        for s in self.waitings:
            conn = self.tcp_conns.sock2conn[s]
            if conn.connectted:
                self.logger.info(
                    'successfully connect to scl_proxy, dst: %s' % conn.conn_id)
                self.waitings.remove(s)
                self.outputs_ctrl.append(s)
            else:
                connectted, err = conn.isconnectted()
                if connectted:
                    self.logger.info(
                        'successfully connect to scl_proxy, dst: %s' % conn.conn_id)
                    self.waitings.remove(s)
                    self.outputs_ctrl.append(s)
                elif err is not errno.EINPROGRESS:
                    self.logger.error(
                            'connect to scl_proxy fails, errno %d, dst: %s' % (
                                err, conn.conn_id))
                    self.clean_outcome_connection(conn.conn_id, s)
                else:
                    self.logger.info(
                            'connecting to scl_proxy, dst: %s' % conn.conn_id)

        # receive connections from scl_agents and other scl_proxies
        if self.tcp_srvr.sock in lists[0]:
            sock, conn_id = self.tcp_srvr.accept()
            self.logger.info('a new connection from %s' % id2str(conn_id))
            self.inputs.append(sock)
            if id2str(conn_id) in self.agent_list and \
                    id2str(conn_id) not in self.streams.link_log.switches():
                self.logger.info(
                    'receive msg of a new switch by scl_agent, '
                    'set up a new connection from proxy to controller')
                self.scl2ctrl.open(conn_id)
                self.outputs_sw.append(sock)

        for s in self.inputs:
            # socket is readable
            if s is self.tcp_srvr.sock:
                continue
            if s in lists[0]:
                conn_id = self.tcp_srvr.sock2conn[s].conn_id
                try:
                    data = s.recv(RECV_BUF_SIZE)
                    if data:
                        ret = scl.scl_tcp_unpack(data, conn_id)
                        for pad, sclt, msg in ret:
                            if not msg:
                                continue
                            self.logger.debug(
                                'receive msg from %s, type: %d' % (
                                        id2str(conn_id), sclt))
                            self.process_msg(conn_id, sclt, msg)
                    else:
                        self.logger.info(
                            'connection closed by %s' % id2str(conn_id))
                        self.clean_income_connection(conn_id, s)
                except socket.error, e:
                    self.logger.error(
                        'connection to switch closed abnormally, error %s' % e)
                    self.clean_income_connection(conn_id, s)

        for s in self.outputs:
            # socket is writeable
            if s in lists[1]:
                conn_id = self.tcp_srvr.sock2conn[s].conn_id
                if not self.streams.downstreams[conn_id].empty():
                    self.logger.debug(
                        'send a msg to scl_agent %s' % id2str(conn_id))
                    msg, sclt = self.streams.downstreams[conn_id].get_nowait()
                    self.send_raw(msg, sclt, id2str(conn_id))

        # reconnect failed socket to other proxies
        if self.timer.time_up:
            for intf in self.dst_intfs:
                if not self.tcp_conns.intf2conn[intf]:
                    self.logger.debug('reopen connection to proxy %s' % intf)
                    self.open(intf)

        # periodically
        self.link_state_rqst()
        self.flow_table_rqst()
        self.flow_table_diff_check()
        if self.fstats:
            self.flow_stats_rqst()
            self.te_routing_trigger()
        self.gossip_syn()
