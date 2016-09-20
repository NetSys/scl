import os
import ConfigParser
import json
from topo import topo2file, FatTree, FatTreeOutBand
from mininet.net import Mininet
from mininet.link import TCLink
from mininet.cli import CLI
from mininet.node import Controller, RemoteController
from mininet.log import setLogLevel

DIR = 'bash scripts'
#LOG_LEVEL = 'info'
LOG_LEVEL = 'debug'
CONF_FILE = '../conf/net.cfg'

class SclNet(object):
    def __init__(self, topo='fattree_outband', app='shortest', ch='udp'):
        self.switches = []
        self.hosts = []
        self.topo = topo
        # NOTE: hard code now, use config file instead
        self.ctrls = [3, 7, 8, 15]
        setLogLevel(LOG_LEVEL)
        # set up topology skeleton
        if self.topo == 'fattree_inband':
            self.skeleton = FatTree(4, self.switches, self.hosts)
        elif self.topo == 'fattree_outband':
            self.skeleton = FatTreeOutBand(4, self.switches, self.hosts, self.ctrls)
        # autoStaticArp doesnt works well, because we will move the IP in
        # the host interface to the internal port of the switch
        self.net = Mininet(topo=self.skeleton, controller=None, link=TCLink)
        # write topology to file
        self.file_name = os.path.abspath('../conf') + '/' + topo + '.json'
        topo2file(self.file_name, self.net, self.switches, self.hosts, self.ctrls)
        self.write_conf_to_file()
        if app == 'clean':
            return
        self.set_static_arps()
        # set up ovs in each switch namespace
        if topo == 'fattree_inband':
            self.start_switch()
            self.start_inband_connection()
            self.config_ctrl_routing('inband')
            self.start_controller(app)
            self.start_scl_proxy(ch)
            self.start_scl_agent(ch)
        if topo == 'fattree_outband':
            self.start_dp_switch()
            self.start_ctrl_switch()
            self.config_ctrl_routing('outband')
            self.start_outband_connection()
            self.start_controller(app)
            self.start_scl_proxy(ch)
            self.start_scl_agent(ch)

    def write_conf_to_file(self):
        agent_list = []
        proxy_list = []
        for sw_name in self.switches:
            sw = self.net.getNodeByName(sw_name)
            agent_list.append(sw.IP())
        for ctrl in self.ctrls:
            host = self.net.getNodeByName(self.hosts[ctrl])
            proxy_list.append(host.IP())
        config = ConfigParser.ConfigParser()
        config.add_section('interfaces')
        config.set('interfaces', 'agent_list', json.dumps(agent_list))
        config.set('interfaces', 'proxy_list', json.dumps(proxy_list))
        with open(CONF_FILE, 'wb') as configfile:
            config.write(configfile)

    def set_static_arps(self):
        ctrls = [self.hosts[ctrl] for ctrl in self.ctrls]
        hosts = [host for host in self.hosts if host not in ctrls]
        arps = []
        for host_name in hosts:
            host = self.net.getNodeByName(host_name)
            arps.append((host.IP(), host.MAC()))
        for host_name in hosts:
            host = self.net.getNodeByName(host_name)
            for arp in arps:
                if arp[0] == host.IP():
                    continue
                host.cmdPrint('arp -s %s %s' % (arp[0], arp[1]))

    def start_scl_agent(self, ch):
        sw_id = 0
        for sw_name in self.switches:
            sw = self.net.getNodeByName(sw_name)
            sw.cmd('cd .. && python ./scl_agent.py %d %s --debug > ./log/scl_agent_%d.log 2>&1 &' % (sw_id, ch, sw_id))
            sw_id = sw_id + 1

    def start_scl_proxy(self, ch):
        ctrl_id = 0
        ctrls_num = len(self.ctrls)
        for ctrl in self.ctrls:
            host = self.net.getNodeByName(self.hosts[ctrl])
            host.cmdPrint('cd .. && python ./scl_proxy.py %d %s --debug > ./log/scl_proxy_%d.log 2>&1 &' % (ctrl_id, ch, ctrl_id))
            ctrl_id = ctrl_id + 1

    def start_controller(self, app):
        ctrl_id = 0
        pox_format='"%(asctime)s - %(name)s - %(levelname)s - %(message)s"'
        pox_datefmt='"%Y%m%d %H:%M:%S"'
        for ctrl in self.ctrls:
            host = self.net.getNodeByName(self.hosts[ctrl])
            # NOTE: hard code
            #host.cmd('python pox/pox.py log.level --DEBUG log --file=log/ctrl_%d.log,w --format=%s --datefmt=%s scl_routing --name=%s &' % (ctrl_id, pox_format, pox_datefmt, self.file_name))
            if app == 'shortest':
                host.cmd('cd .. && python pox/pox.py log.level --DEBUG log --format=%s --datefmt=%s scl_routing --name=%s > log/ctrl_%d.log 2>&1 &' % (pox_format, pox_datefmt, self.file_name, ctrl_id))
            elif app == 'te':
                host.cmd('cd .. && python pox/pox.py log.level --DEBUG log --format=%s --datefmt=%s scl_te --name=%s > log/ctrl_%d.log 2>&1 &' % (pox_format, pox_datefmt, self.file_name, ctrl_id))
            ctrl_id = ctrl_id + 1

    def start_switch(self):
        for sw_name in self.switches:
            sw = self.net.getNodeByName(sw_name)
            sw.cmdPrint('%s/start_ovs.sh %s' % (DIR, sw_name))
            sw.cmdPrint('%s/create_br.sh %s' % (DIR, sw_name))

    def start_dp_switch(self):
        for sw_name in self.switches:
            sw = self.net.getNodeByName(sw_name)
            sw.cmdPrint('%s/start_ovs.sh %s' % (DIR, sw_name))
            sw.cmdPrint('%s/create_dp_br.sh %s' % (DIR, sw_name))

    def start_ctrl_switch(self):
        for sw_name in self.switches:
            sw_name = 'c' + sw_name[1:]
            sw = self.net.getNodeByName(sw_name)
            sw.cmdPrint('%s/start_ovs.sh %s' % (DIR, sw_name))
            sw.cmdPrint('%s/create_ctrl_br.sh %s' % (DIR, sw_name))

    def config_ctrl_routing(self, topo):
        for ctrl in self.ctrls:
            host = self.net.getNodeByName(self.hosts[ctrl])
            ip = host.IP()
            # config ip to control plane interface
            # add default route to send broadcast msg
            if topo == 'outband':
                host.cmdPrint('ifconfig %s-eth0 0' % self.hosts[ctrl])
                host.cmdPrint('ifconfig %s-eth1 %s/8' % (self.hosts[ctrl], ip))
                host.cmdPrint('route add default gw %s'% ip)
            elif topo == 'inband':
                host.cmdPrint('route add -host 255.255.255.255 dev %s-eth0' % self.hosts[ctrl])

    def config_ctrl_vlan(self):
        # set vlan to some sw ports which connect to controller hosts
        for ctrl in self.ctrls:
            host = self.net.getNodeByName(self.hosts[ctrl])
            host_intf = host.intfList()[0]
            sw_intf = host_intf.link.intf1\
                    if host_intf.link.intf1 is not host_intf\
                    else host_intf.link.intf2
            sw_name = sw_intf.name.split('-')[0]
            sw = self.net.getNodeByName(sw_name)
            # sw.ports index starts from 0, ovs index starts from 1
            sw_port = sw.ports[sw_intf] + 1
            port_list = [1,2,3,4]
            port_list.remove(sw_port)
            self.net.getNodeByName(sw_name).cmdPrint(
                    '%s/config_ctrl_vlan.sh %s %s %d %d %d %d' % (
                        DIR, sw_name, sw_intf.name, sw_port, port_list[0], port_list[1], port_list[2]))

    def start_inband_connection(self):
        sw = self.net.getNodeByName(self.switches[3])
        #sw.cmdPrint('tcpdump -i lo -enn -w s003.pcap &')
        for sw_name in self.switches:
            sw = self.net.getNodeByName(sw_name)
            sw.cmdPrint('%s/start_inband_connection.sh %s' % (DIR, sw_name))
        self.config_ctrl_vlan()

    def start_outband_connection(self):
        sw = self.net.getNodeByName(self.switches[3])
        #sw.cmdPrint('tcpdump -i lo -enn -w s003.pcap &')
        for sw_name in self.switches:
            sw = self.net.getNodeByName(sw_name)
            sw_intf = sw.intfList()[-1]
            ctrl_intf = sw_intf.link.intf1\
                    if sw_intf.link.intf1 is not sw_intf\
                    else sw_intf.link.intf2
            ctrl_name = ctrl_intf.name.split('-')[0]
            assert ctrl_name[0] == 'c'
            output = sw.ports[sw_intf] + 1
            sw.cmdPrint(
                    '%s/start_outband_connection.sh %s %d' % (
                        DIR, sw_name, output))

    def run(self):
        CLI(self.net)

    def clearSwitches(self):
        sw = self.net.getNodeByName(self.switches[0])
        sw.cmdPrint('%s/stop_scl.sh' % DIR)
        sw.cmdPrint('ps -ef | grep scl')
        sw.cmdPrint('ps -ef | grep pox')
        for sw_name in self.switches:
            sw = self.net.getNodeByName(sw_name)
            sw.cmdPrint('%s/clear_all.sh %s' % (DIR, sw_name))
        if self.topo == 'fattree_outband':
            for sw_name in self.switches:
                sw_name = 'c' + sw_name[1:]
                sw = self.net.getNodeByName(sw_name)
                sw.cmdPrint('%s/clear_all.sh %s' % (DIR, sw_name))

    def stop(self):
        self.clearSwitches()
        self.net.stop()
