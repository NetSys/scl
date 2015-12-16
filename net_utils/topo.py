import json
import networkx as nx
from mininet.topo import Topo

def topo2file(file_name, net, switches, hosts, ctrls):
    data = {}
    data['hosts'] = {}
    for host_name in hosts:
        host = net.getNodeByName(host_name)
        data['hosts'][host_name] = host.IP()
    data['switches'] = switches
    data['ctrls'] = [hosts[ctrl] for ctrl in ctrls]
    links = set()
    for sw_name in switches:
        sw = net.getNodeByName(sw_name)
        for intf in sw.intfList():
            if intf.name is not 'lo':
                port = sw.ports[intf] + 1
                another_intf = intf.link.intf1\
                        if intf.link.intf1 is not intf else intf.link.intf2
                another_sw_name = another_intf.name.split('-')[0]
                if another_sw_name[0] == 'c' or another_sw_name in data['ctrls']:
                    continue
                another_sw = net.getNodeByName(another_sw_name)
                another_port = another_sw.ports[another_intf] + 1
                if intf is intf.link.intf1:
                    port1, port2 = port, another_port
                else:
                    port2, port1 = port, another_port
                links.add((
                    intf.link.intf1.name, port1, intf.link.intf2.name, port2))
    data['links'] = list(links)
    with open(file_name, 'w') as out_file:
        json.dump(data, out_file)

class FatTree(Topo):
    def __init__(self, pod, switches, hosts):
        self.pod = pod
        self.core_num = (pod / 2) ** 2
        self.aggr_num = pod * pod / 2
        self.edge_num = pod * pod / 2
        self.host_num = ((pod / 2) ** 2) * pod
        self.core_list = []
        self.aggr_list = []
        self.edge_list = []
        self.switch_list = switches
        self.host_list = hosts
        super(FatTree, self).__init__()
        self.create()

    def createSwitches(self):
        num = self.core_num + self.aggr_num + self.edge_num
        for i in xrange(0, num):
            sw = 's' + str(i).zfill(3)          # 3: switch number length
            sw_ip = '10.0.%s.1/8' % str(i)      # internal port ip addr
            self.switch_list.append(sw)
            self.addHost(sw, ip=sw_ip)
            if i < self.core_num:
                self.core_list.append(sw)
            elif i < self.core_num + self.aggr_num:
                self.aggr_list.append(sw)
            else:
                self.edge_list.append(sw)

    def createHosts(self):
        for i in xrange(0, self.host_num):
            host = 'h' + str(i).zfill(3)        # 3: host number length
            host_ip = '10.1.%s.1/8' % str(i)
            self.host_list.append(host)
            self.addHost(host, ip=host_ip)

    def createLinks(self):
        # core <--> aggregation
        index = 0
        for aggr in self.aggr_list:
            for i in xrange(0, self.pod / 2):
                self.addLink(aggr, self.core_list[index], )
                index = (index + 1) % self.core_num

        # aggregation <--> edge
        for i in xrange(0, self.aggr_num, self.pod / 2):
            for j in xrange(0, self.pod / 2):
                for k in xrange(0, self.pod / 2):
                    self.addLink(self.aggr_list[i + j], self.edge_list[i + k], )

        # edge <--> host
        index = 0
        for edge in self.edge_list:
            for i in xrange(0, self.pod / 2):
                self.addLink(edge, self.host_list[index], )
                index = index + 1

    def create(self):
        self.createSwitches()
        self.createHosts()
        self.createLinks()


class FatTreeOutBand(FatTree):
    def __init__(self, pod, switches, hosts, ctrls):
        super(FatTreeOutBand, self).__init__(pod, switches, hosts)
        self.createControlSwitches()
        self.createControlLinks(ctrls)

    def createControlSwitches(self):
        num = self.core_num + self.aggr_num + self.edge_num
        for i in xrange(0, num):
            sw = 'c' + str(i).zfill(3)          # 3: switch number length
            sw_ip = '10.2.%s.1/8' % str(i)
            self.addHost(sw, ip=sw_ip)

    def createControlLinks(self, ctrls):
        ctrl_hosts = [self.host_list[ctrl] for ctrl in ctrls]
        for edge in self.g.edges():
            host1, host2 = edge[0], edge[1]
            if host1[0] == 's' and host2[0] == 's':
                ctrl_sw1 = 'c' + host1[1:]
                ctrl_sw2 = 'c' + host2[1:]
                self.addLink(ctrl_sw1, ctrl_sw2, )
            else:
                if host1 in ctrl_hosts:
                    ctrl_sw = 'c' + host2[1:]
                    self.addLink(host1, ctrl_sw)
                elif host2 in ctrl_hosts:
                    ctrl_sw = 'c' + host1[1:]
                    self.addLink(host2, ctrl_sw)

        for switch in self.switch_list:
            ctrl_sw = 'c' + switch[1:]
            self.addLink(ctrl_sw, switch)
