import socket
import struct
import random
import json
import libopenflow_01 as of
from socket_utils import *
from conf.const import RECV_BUF_SIZE, WINDOW
from collections import defaultdict


def byteify(input):
    '''
    convert unicode from json.loads to utf-8
    '''
    if isinstance(input, dict):
        return {byteify(key): byteify(value) for key, value in input.iteritems()}
    elif isinstance(input, list):
        return [byteify(element) for element in input]
    elif isinstance(input, unicode):
        return input.encode('utf-8')
    else:
        return input


class LinkLog(object):
    def __init__(self, host_id, hosts_num):
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


gossiper_seq = of.xid_generator()
HEADER_SIZE = 6

class Gossiper(object):
    def __init__(
            self, scl_gossip_mcast_grp, scl_gossip_mcast_port, scl_gossip_intf,
            scl2ctrl, host_id, timer, streams, logger):
        self.udp_mcast = UdpMcastListener(
                scl_gossip_mcast_grp, scl_gossip_mcast_port, scl_gossip_intf)
        self.udp_mcast.open()
        self.scl2ctrl = scl2ctrl
        self.timer = timer
        self.streams = streams
        self.link_log = streams.link_log
        self.logger = logger
        self.buffs = defaultdict(lambda: defaultdict(lambda: None))
        self.version = defaultdict(lambda: None)
        self.msgs_num = defaultdict(lambda: 0)

    def _open(self, host_id, peer_lists):
        '''
        deprecated
        '''
        self.sock = socket.socket(
                socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.sock.setblocking(0)            # non-blocking
        self.sock.bind(peer_lists[host_id])
        del peer_lists[host_id]
        self.peer_lists = peer_lists

    def _handle_msg(self, data, addr_id):
        '''
                 **pull method**
        |---       syn, digest        -->|
        |                                |
        |<-- ack, response of missing ---|
        '''
        if data['type'] == 'syn':
            self._handle_syn(data, addr_id)
        elif data['type'] == 'ack':
            self._handle_ack(data, addr_id)

    def _handle_syn(self, data, addr_id):
        addr = id2str(addr_id)
        self.logger.debug(
                "receive syn from %s, digest: %s" % (
                    addr, json.dumps(data['digest'])))

        delta = self.link_log.subtract_log(data['digest'])

        if delta:
            self.logger.debug(
                    "send ack to %s, delta: %s" % (
                        addr, json.dumps(delta)))
            self.send(json.dumps({'type': 'ack', 'delta': delta}), addr_id)

    def _handle_ack(self, data, addr_id):
        addr = id2str(addr_id)
        self.logger.debug(
                "receive ack from %s, delta: %s" % (
                    addr, json.dumps(data['delta'])))
        for switch in data['delta']:
            for link in data['delta'][switch]:
                for event, items in data['delta'][switch][link].iteritems():
                    event = int(event)
                    if switch not in self.link_log.switches():
                        self.logger.info(
                                'receive link msg of a new switch by gossiper, '
                                'set up a new connection from proxy to controller')
                        self.scl2ctrl.open(str2id(switch))
                    ret = self.link_log.update(switch, link, event, items['state'], addr)
                    if ret:
                        self.streams.upcall_link_status(ret[0], ret[1], ret[2])
                    for peer in items['peers']:
                        self.link_log.update(switch , link, event, items['state'], peer)

    def _add_header(self, data, ver, idx, num):
        data = struct.pack('!I', ver) + struct.pack('!B', idx) +\
               struct.pack('!B', num) + data
        return data

    def _parse_data(self, data):
        ver = ord(data[0]) << 24 + ord(data[1]) << 16 + ord(data[2]) << 8 + ord(data[3])
        idx = ord(data[4])
        num = ord(data[5])
        msg = data[6:]
        return ver, idx, num, msg

    def send(self, data, addr=None):
        msgs = []
        max_msg_length = RECV_BUF_SIZE - HEADER_SIZE
        while len(data) > max_msg_length:
            msgs.append(data[0: max_msg_length])
            data = data[max_msg_length:]
        msgs.append(data)
        msgs_num = len(msgs)
        version = gossiper_seq()
        for i in xrange(0, msgs_num):
            msgs[i] = self._add_header(msgs[i], version, i, msgs_num)
            if addr:
                self.udp_mcast.send_to_id(msgs[i], addr)
            else:
                self.udp_mcast.multicast(msgs[i])

    def _check_completeness(self, addr_id):
        if len(self.buffs[addr_id]) == self.msgs_num[addr_id]:
            complete_msg = ''
            for i in xrange(0, self.msgs_num[addr_id]):
                complete_msg += self.buffs[addr_id][i]
            self._handle_msg(byteify(json.loads(complete_msg)), addr_id)
            del self.version[addr_id]
            del self.msgs_num[addr_id]
            del self.buffs[addr_id]

    def recv(self):
        data, addr_id = self.udp_mcast.recvfrom(RECV_BUF_SIZE)
        version, index, num, msg = self._parse_data(data)
        if not self.version[addr_id]:
            # new version, last msg has been processed
            self.version[addr_id] = version
            self.msgs_num[addr_id] = num
            self.buffs[addr_id][index] = msg
            self._check_completeness(addr_id)
        else:
            if version == self.version[addr_id]:
                # the same version, last msg to be processed
                if self.msgs_num[addr_id] != num:
                    self.logger.error("msgs in the same version (%d) have different msg num" % version)
                    del self.version[addr_id]
                    del self.msgs_num[addr_id]
                    del self.buffs[addr_id]
                else:
                    self.buffs[addr_id][index] = msg
                    self._check_completeness(addr_id)
            elif (version > self.version[addr_id] and version - self.version[addr_id] < WINDOW) or\
                 (version < self.version[addr_id] and self.version[addr_id] - version > WINDOW):
                # new version is larger that current one
                # and not a new cycle (current version is not small enough)
                # or
                # new version is smaller that current one
                # and a new cycle begins (new version is small enough)
                # then
                # discard current states, and update msg version and msg
                self.version[addr_id] = version
                self.msgs_num[addr_id] = num
                del self.buff[addr_id]
                self.buffs[addr_id][index] = msg
                self._check_completeness(addr_id)

    def wait(self, selector):
        selector.wait([self.udp_mcast.sock], [])

    def run(self, lists):
        # socket is readable
        if self.udp_mcast.sock in lists[0]:
            self.logger.info("current link log: %s" % json.dumps(self.link_log.log))
            self.recv()

        # check timer, time up per second
        if self.timer.time_up:
            self.logger.debug(
                    "broadcast syn, digest: %s" % (
                        json.dumps(self.link_log.digest())))
            self.send(json.dumps({'type': 'syn', 'digest': self.link_log.digest()}))
