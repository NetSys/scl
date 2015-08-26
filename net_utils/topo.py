from mininet.topo import Topo


class FatTree(Topo):
    def __init__(self, pod, graph, switches, hosts):
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
        self.graph = graph
        super(FatTree, self).__init__()
        self.create()

    def createSwitches(self):
        num = self.core_num + self.aggr_num + self.edge_num
        for i in xrange(0, num):
            sw = 's' + str(i).zfill(3)          # 3: switch number length
            sw_ip = '10.0.%s.1/8' % str(i)      # internal port ip addr
            self.graph.add_node(sw)
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
            self.graph.add_node(host)
            self.host_list.append(host)
            self.addHost(host, ip=host_ip)

    def createLinks(self):
        # core <--> aggregation
        index = 0
        for aggr in self.aggr_list:
            for i in xrange(0, self.pod / 2):
                self.graph.add_edge(aggr, self.core_list[index])
                self.addLink(aggr, self.core_list[index], )
                index = (index + 1) % self.core_num

        # aggregation <--> edge
        for i in xrange(0, self.aggr_num, self.pod / 2):
            for j in xrange(0, self.pod / 2):
                for k in xrange(0, self.pod / 2):
                    self.graph.add_edge(
                            self.aggr_list[i + j], self.edge_list[i + k])
                    self.addLink(self.aggr_list[i + j], self.edge_list[i + k], )

        # edge <--> aggregation
        index = 0
        for edge in self.edge_list:
            for i in xrange(0, self.pod / 2):
                self.graph.add_edge(edge, self.host_list[index])
                self.addLink(edge, self.host_list[index], )
                index = index + 1

    def create(self):
        self.createSwitches()
        self.createHosts()
        self.createLinks()
