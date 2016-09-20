## SCL (Simple Coordination Layer)

SCL composes of SCL-agent running at each switch and SCL-proxy running at each single-image controller like POX.

## Running SCL in Machines

SCL-agent: copy `conf/` `lib/` `log/` and `scl_agent.py` to the destination environment.

``` Bash
./scl_agent.py <id> udp
```

SCL-proxy: copy `conf/` `lib/` `log` and `scl_proxy.py` to the destination environment.

``` Bash
./scl_proxy.py <id> udp
```

Controller: two applications, shortest path routing and traffic engineering, are implemented on top of POX. To avoid POX flushes the flow entries on switches, comment the following codes.
``` Bash
# file: pox/pox/openflow/of_01.py
148 # if con.ofnexus.clear_flows_on_connect:
149 #   con.send(of.ofp_flow_mod(match=of.ofp_match(), command=of.OFPFC_DELETE))
```

Configuration: IP addresses of SCL-agents and SCL-proxies are specified in `conf/net.cfg`. Change these addresses according to the local network configuration. Default UDP broadcast address and controller listening address are specified in `conf/const.py`. To run the POX application, a topology configuration file in needed, or enable LLDP module instead.

Addtion: some scripts in `cloudlab` directory for configuring and running SCL remotely and a shortest path routing application implemented on top of ONOS in `onos` directory.

## Running SCL in Mininet

SCL can be tested in Mininet with a Fat-tree inbound/outband topology locally. Install Mininet and download POX into `pox/` directory first.

``` Bash
cd mininet && sudo ./run.py udp fattree_inband shortest
```
