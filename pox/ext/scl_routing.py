import json
import networkx as nx
import pox.openflow.libopenflow_01 as of
from collections import defaultdict
from pox.core import core
from pox.lib.util import dpid_to_str
from pox.lib.addresses import IPAddr

log = core.getLogger()

def dpid2name(dpid):
    return 's' + str(dpid).zfill(3)


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


class Link(object):
    def __init__(
            self, intf1, port1, intf2, port2,
            state1=of.OFPPS_LINK_DOWN, state2=of.OFPPS_LINK_DOWN):
        self.intf1 = intf1
        self.port1 = port1
        self.state1 = state1
        self.sw1 = intf1.split('-')[0]
        self.intf2 = intf2
        self.port2 = port2
        self.sw2 = intf2.split('-')[0]
        self.state2 = state2
        # default host link state is up
        if self.sw1[0] == 'h':
            self.state1 = of.OFPPS_STP_FORWARD
        if self.sw2[0] == 'h':
            self.state2 = of.OFPPS_STP_FORWARD


class scl_routing(object):
    '''
    proactive mode: update routing table according to link states
    '''
    def __init__(self, name):
        self.topo = None
        self.graph = nx.Graph()
        self.hosts = {}         # [host] --> host_ip
        self.sw2conn = {}       # [sw] --> connection
        # [intf] --> link_obj
        self.intf2link = defaultdict(lambda: None)
        # [sw1][sw2] --> link_obj
        self.sw2link = defaultdict(lambda: defaultdict(lambda: None))
        # [sw][host1][host2] --> link_obj
        self.sw_tables = defaultdict(
                lambda: defaultdict(lambda: defaultdict(lambda: None)))
        # [sw][host1][host2] --> update_status
        self.sw_tables_status = defaultdict(
                lambda: defaultdict(lambda: defaultdict(lambda: None)))
        self.load_topo(name)
        core.openflow.addListeners(self)

    def load_topo(self, name):
        with open(name) as in_file:
            self.topo = byteify(json.load(in_file))
            if self.topo:
                for host in self.topo['hosts'].keys():
                    if host not in self.topo['ctrls']:
                        self.graph.add_node(host)
                        self.hosts[host] = self.topo['hosts'][host]
                log.debug('total edge num: %d' % len(self.topo['links']))
                for link in self.topo['links']:
                    intf1, port1, intf2, port2 = link[0], link[1], link[2], link[3]
                    sw1 = intf1.split('-')[0]
                    sw2 = intf2.split('-')[0]
                    link_obj = Link(intf1, port1, intf2, port2)
                    self.sw2link[sw1][sw2] = link_obj
                    self.intf2link[intf1] = link_obj
                    self.sw2link[sw2][sw1] = link_obj
                    self.intf2link[intf2] = link_obj

    def graph_add_edge(self, sw1, sw2):
        self.graph.add_edge(sw1, sw2, weight=1)

    def _handle_ConnectionUp(self, event):
        log.debug("Switch %s up.", dpid_to_str(event.dpid))
        sw_name = dpid2name(event.dpid)
        if sw_name not in self.topo['switches']:
            log.error('sw: %s not in topology' % sw_name)
            return
        if self.graph.has_node(sw_name):
            log.error('sw: %s is in current graph' % sw_name)
            return
        self.graph.add_node(sw_name)
        self.sw2conn[sw_name] = event.connection

    def _handle_ConnectionDown(self, event):
        log.debug("Switch %s down.", dpid_to_str(event.dpid))
        sw_name = dpid2name(event.dpid)
        if not self.graph.has_node(sw_name):
            log.error('sw: %s is not in current graph' % sw_name)
            return
        self.graph.remove_node(sw_name)
        del self.sw2conn[sw_name]
        for sw2 in self.sw2link[sw_name]:
            link = self.sw2link[sw_name][sw2]
            if sw_name is link.sw1:
                link.state1 = of.OFPPS_LINK_DOWN
            else:
                link.state2 = of.OFPPS_LINK_DOWN
        self.update_flow_tables(self._calculate_shortest_route())

    def _handle_PortStatus(self, event):
        assert event.modified is True
        log.debug("Switch %s portstatus upcall.", dpid_to_str(event.dpid))
        log.debug("     port: %s, state: %d" % (event.ofp.desc.name, event.ofp.desc.state))
        link = self.intf2link[event.ofp.desc.name]
        if not link:
            log.debug('control <---> data link intf')
            return
        sw1, sw2 = link.sw1, link.sw2
        old_state = link.state1 if event.ofp.desc.name == link.intf1 else link.state2
        if event.ofp.desc.state != of.OFPPS_LINK_DOWN:
            # we do not distinguish stp state types
            event.ofp.desc.state = of.OFPPS_STP_FORWARD
        if event.ofp.desc.state == old_state:
            log.debug("intf %s state is already %d" % (event.ofp.desc.name, old_state))
            return
        if event.ofp.desc.state != of.OFPPS_LINK_DOWN:
            if event.ofp.desc.name == link.intf1:
                link.state1 = event.ofp.desc.state
                if link.state2 != of.OFPPS_LINK_DOWN:
                    # both ends of the link are up, update route
                    log.debug("both ends of the link are up, add edge %s %s" % (sw1, sw2))
                    self.graph_add_edge(sw1, sw2)
                    self.update_flow_tables(self._calculate_shortest_route())
                else:
                    log.debug('one end of the link is up, wait for the other end')
                    return
            else:
                link.state2 = event.ofp.desc.state
                if link.state1 != of.OFPPS_LINK_DOWN:
                    # both ends of the link are up, update route
                    log.debug("both ends of the link are up, add edge %s %s" % (sw1, sw2))
                    self.graph_add_edge(sw1, sw2)
                    self.update_flow_tables(self._calculate_shortest_route())
                else:
                    log.debug('one end of the link is up, wait for the other end')
                    return
        else:
            if event.ofp.desc.name == link.intf1:
                link.state1 = event.ofp.desc.state
                if link.state2 != of.OFPPS_LINK_DOWN:
                    # an end of the link is down, update route
                    log.debug("one end of the link is down, remove edge %s %s" % (sw1, sw2))
                    self.graph.remove_edge(sw1, sw2)
                    self.update_flow_tables(self._calculate_shortest_route())
                else:
                    log.debug('both ends of the link are down')
                    return
            else:
                link.state2 = event.ofp.desc.state
                if link.state1 != of.OFPPS_LINK_DOWN:
                    # an end of the link is down, update route
                    log.debug("one end of the link is down, remove edge %s %s" % (sw1, sw2))
                    self.graph.remove_edge(sw1, sw2)
                    self.update_flow_tables(self._calculate_shortest_route())
                else:
                    log.debug('both ends of the link are down')
                    return

    def _calculate_shortest_route(self):
        log.debug("calculate shortest path routing...")
        log.debug("edges, num %d: %s", len(self.graph.edges()), json.dumps(self.graph.edges()))
        updates = {'modify': defaultdict(lambda: []), 'delete' : defaultdict(lambda: [])}
        current = 0
        for host1 in self.hosts:
            for host2 in self.hosts:
                if host1 is host2:
                    continue
                try:
                    paths = list(nx.all_shortest_paths(self.graph, host1, host2, 'weight'))
                except nx.exception.NetworkXNoPath:
                    continue
                path = paths[current % len(paths)]
                current += 1
                log.debug('calculated path: %s' % json.dumps(path))
                path = zip(path, path[1:])
                for (a, b) in path[1:]:
                    link = self.sw2link[a][b]
                    if self.sw_tables[a][host1][host2] != link:
                        self.sw_tables[a][host1][host2] = link
                        updates['modify'][a].append((host1, host2, link))
                        self.sw_tables_status[a][host1][host2] = 'updated'
                    else:
                        self.sw_tables_status[a][host1][host2] = 'checked'
        for sw in self.sw_tables_status.keys():
            for host1 in self.sw_tables_status[sw].keys():
                for host2 in self.sw_tables_status[sw][host1].keys():
                    if self.sw_tables_status[sw][host1][host2] is not 'updated' and\
                       self.sw_tables_status[sw][host1][host2] is not 'checked':
                        updates['delete'][sw].append((
                            host1, host2, self.sw_tables[sw][host1][host2]))
                        del self.sw_tables[sw][host1][host2]
                        del self.sw_tables_status[sw][host1][host2]
                    else:
                        self.sw_tables_status[sw][host1][host2] = 'to_be_deleted'
        return updates

    def update_flow_entry(self, sw_name, host1, host2, link, cmd):
        nw_src = self.hosts[host1]
        nw_dst = self.hosts[host2]
        # types of sw_name and link.sw1 are different, use == not is
        if sw_name == link.sw1:
            log.debug(
                    'host1 %s --> host2 %s; link: %s %s %d --> %s %s %d' % (
                        nw_src, nw_dst, link.sw1, link.intf1, link.port1, link.sw2, link.intf2, link.port2))
            outport = link.port1
        else:
            log.debug(
                    'host1 %s --> host2 %s; link: %s %s %d --> %s %s %d' % (
                        nw_src, nw_dst, link.sw2, link.intf2, link.port2, link.sw1, link.intf1, link.port1))
            outport = link.port2
        msg = of.ofp_flow_mod(command = cmd)
        msg.match.dl_type = 0x800
        msg.match.nw_src = IPAddr(nw_src)
        msg.match.nw_dst = IPAddr(nw_dst)
        msg.priority = 50000    # hard code
        msg.actions.append(of.ofp_action_output(port = outport))
        if sw_name in self.sw2conn:
            self.sw2conn[sw_name].send(msg.pack())

    def update_flow_tables(self, updates):
        if not updates['modify'] and not updates['delete']:
            return
        log.debug("update flow tables")

        for sw_name, flow_entries in updates['modify'].iteritems():
            log.debug('modify sw flow_entries: %s' % sw_name)
            for host1, host2, link in flow_entries:
                self.update_flow_entry(sw_name, host1, host2, link, of.OFPFC_MODIFY)

        for sw_name, flow_entries in updates['delete'].iteritems():
            log.debug('delete sw flow_entries: %s' % sw_name)
            for host1, host2, link in flow_entries:
                self.update_flow_entry(sw_name, host1, host2, link, of.OFPFC_DELETE)


def launch(name=None):
    if not name:
        log.info('input topology configuration file first')
        return
    core.registerNew(scl_routing, name)
