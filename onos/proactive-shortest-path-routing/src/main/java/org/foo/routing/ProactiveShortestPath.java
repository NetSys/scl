/*
 * Copyright 2016-present Open Networking Laboratory
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
package org.foo.routing;

import org.apache.felix.scr.annotations.Activate;
import org.apache.felix.scr.annotations.Component;
import org.apache.felix.scr.annotations.Deactivate;
import org.apache.felix.scr.annotations.Reference;
import org.apache.felix.scr.annotations.ReferenceCardinality;
import org.onlab.packet.Ethernet;
import org.onlab.packet.IPv4;
import org.onlab.packet.IpPrefix;
import org.onlab.packet.Ip4Prefix;
import org.onlab.graph.Vertex;
import org.onlab.graph.Edge;
import org.onlab.graph.Path;
import org.onlab.graph.EdgeWeight;
import org.onlab.graph.AbstractGraphPathSearch;
import org.onlab.graph.MutableAdjacencyListsGraph;
import org.onlab.graph.DijkstraGraphSearch;
import org.onlab.graph.Graph;
import org.onlab.graph.GraphPathSearch;
import org.onosproject.core.ApplicationId;
import org.onosproject.core.CoreService;
import org.onosproject.net.device.DeviceService;
import org.onosproject.net.DeviceId;
import org.onosproject.net.PortNumber;
import org.onosproject.net.flow.DefaultTrafficSelector;
import org.onosproject.net.flow.DefaultTrafficTreatment;
import org.onosproject.net.flow.FlowEntry;
import org.onosproject.net.flow.FlowRule;
import org.onosproject.net.flow.DefaultFlowRule;
import org.onosproject.net.flow.FlowRuleService;
import org.onosproject.net.flow.TrafficSelector;
import org.onosproject.net.flow.TrafficTreatment;
import org.onosproject.net.flow.criteria.Criterion;
import org.onosproject.net.flow.criteria.IPCriterion;
import org.onosproject.net.flow.instructions.Instruction;
import org.onosproject.net.flow.instructions.Instructions.OutputInstruction;
import org.onosproject.net.flowobjective.DefaultForwardingObjective;
import org.onosproject.net.flowobjective.FlowObjectiveService;
import org.onosproject.net.flowobjective.ForwardingObjective;
import org.onosproject.net.link.LinkEvent;
import org.onosproject.net.link.LinkListener;
import org.onosproject.net.link.LinkService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.Objects;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.HashSet;
import java.util.Iterator;
import java.io.FileReader;
import java.io.FileNotFoundException;
import java.io.IOException;
import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import org.apache.commons.io.IOUtils;
import org.json.JSONObject;
import org.json.JSONArray;
import org.json.JSONException;

//import org.apache.sling.commons.json.JSONObject;
//import org.apache.sling.commons.json.JSONArray;

import static org.onlab.graph.GraphPathSearch.ALL_PATHS;
import static com.google.common.base.MoreObjects.toStringHelper;
import static com.google.common.base.MoreObjects.ToStringHelper;

/**
 * Skeletal ONOS application component.
 */
@Component(immediate = true)
public class ProactiveShortestPath {

    private static final int DEFAULT_PRIORITY = 40000;

    private static final int FLOWENTRY_CHECKED = 1;
    private static final int FLOWENTRY_UPDATED = 2;
    private static final int FLOWENTRY_UPDATED_AND_DELETED = 3;
    private static final int FLOWENTRY_DELETED = 4;
    private static final int FLOWENTRY_WAITING = 5;

    private static final int LINK_UP = 1;
    private static final int LINK_DOWN = 2;

    private static final String topoFileName =
        System.getProperty("user.home") + "/fattree_outband_cloudlab.json";

    // JSON FILE Sample
    // topo = {
    //          'hosts': {'h000': '10.0.0.1', ...},
    //          'switches_dpid_to_name': {'of:0000000000000001': 's000', ...},
    //          'switches_name_to_dpid': {'s000': 'of:0000000000000001', ...},
    //          'links': [['s000', 'eth1', 's002', 'eth3'], ...]
    //      }
    private JSONObject topo;
    private JSONObject hosts;
    private JSONObject switchesDpidToName;
    private JSONObject switchesNameToDpid;
    private final LinkInfo linkInfo = new LinkInfo();

    private final NetFlowEntries flowTables = new NetFlowEntries();
    private HashSet<StringVertex> vertex = new HashSet<StringVertex>();
    private HashSet<StringEdge> edge = new HashSet<StringEdge>();
    private final MutableAdjacencyListsGraph<StringVertex, StringEdge> graph =
        new MutableAdjacencyListsGraph<StringVertex, StringEdge>(vertex, edge);
    private final EqualEdgeWeight equalWeight = new EqualEdgeWeight();

    private Logger log = LoggerFactory.getLogger(getClass());

    @Reference(cardinality = ReferenceCardinality.MANDATORY_UNARY)
    protected DeviceService deviceService;

    @Reference(cardinality = ReferenceCardinality.MANDATORY_UNARY)
    protected FlowRuleService flowRuleService;

    @Reference(cardinality = ReferenceCardinality.MANDATORY_UNARY)
    protected FlowObjectiveService flowObjectiveService;

    @Reference(cardinality = ReferenceCardinality.MANDATORY_UNARY)
    protected LinkService linkService;

    @Reference(cardinality = ReferenceCardinality.MANDATORY_UNARY)
    protected CoreService coreService;

    private final LinkListener linkListener = new InternalLinkListener();

    private ApplicationId appId;

    @Activate
    public void activate() {
        if (linkService == null || coreService == null) {
            log.info("Started error");
            return;
        }

        loadTopology();
        appId = coreService.registerApplication("org.foo.routing");
        linkService.addListener(linkListener);

        log.info("ProactiveShortestPathStarted");
    }

    @Deactivate
    public void deactivate() {
        if (linkService == null || flowRuleService == null) {
            log.info("Stopped error");
            return;
        }

        flowRuleService.removeFlowRulesById(appId);
        linkService.removeListener(linkListener);

        log.info("ProactiveShortestPathStopped");
    }

    private void loadTopology() {
        try {
            File f = new File(topoFileName);
            if (f.exists()) {
                InputStream is = new FileInputStream(topoFileName);
                String jsonString = IOUtils.toString(is);
                topo = new JSONObject(jsonString);
            }
            hosts = (JSONObject) topo.get("hosts");
            switchesDpidToName = (JSONObject) topo.get("switches_dpid_to_name");
            switchesNameToDpid = (JSONObject) topo.get("switches_name_to_dpid");
            Iterator<String> hostsKeys = hosts.keys();
            while (hostsKeys.hasNext()) {
                String hostName = (String) hostsKeys.next();
                graph.addVertex(new StringVertex(hostName));
            }
            Iterator<String> switchesDpidToNameKeys =
                switchesDpidToName.keys();
            while (switchesDpidToNameKeys.hasNext()) {
                String dpid = (String) switchesDpidToNameKeys.next();
                String name = (String) switchesDpidToName.get(dpid);
                flowTables.addSwitch(name);
                graph.addVertex(new StringVertex(name));
            }
            log.info("loaded linkInfo hosts {}, switchesDpidToName {}",  hosts, switchesDpidToName);
            JSONArray links = (JSONArray) topo.get("links");
            for (int i = 0; i < links.length(); i++) {
                JSONArray currentLink = links.getJSONArray(i);
                String sw1 = (String) currentLink.get(0);
                long portNo1 = (long) currentLink.getLong(2);
                String sw2 = (String) currentLink.get(3);
                long portNo2 = (long) currentLink.getLong(5);
                linkInfo.loadLink(sw1, sw2, portNo1, portNo2);
                if (sw1.charAt(0) == 'h' || sw2.charAt(0) == 'h') {
                    graph.addEdge(new StringEdge(sw1, sw2));
                    graph.addEdge(new StringEdge(sw2, sw1));
                    linkInfo.updateSrcStatus(sw1, sw2, LINK_UP);
                    linkInfo.updateSrcStatus(sw2, sw1, LINK_UP);
                }
            }
            log.info("loaded linkInfo links {}", links);
            log.info("current graph {}", graph);
        } catch (FileNotFoundException e) {
            log.info("FileNotFoundException");
            e.printStackTrace();
        } catch (IOException e) {
            log.info("IOException");
            e.printStackTrace();
        } catch (JSONException e) {
            log.info("JSONException");
            e.printStackTrace();
        }
    }

    private class InternalLinkListener implements LinkListener {
        @Override
        public void event(LinkEvent event) {
            try {
                String srcName = (String) switchesDpidToName.get(event.subject().src().deviceId().toString());
                String dstName = (String) switchesDpidToName.get(event.subject().dst().deviceId().toString());
                log.info("new link event: {} <--> {}, srcport: {}", srcName, dstName, event.subject().src().port());
                if (event.type() == LinkEvent.Type.LINK_REMOVED) {
                    log.info("LINK_REMOVED");
                    if (linkInfo.updateSrcStatus(srcName, dstName, LINK_DOWN)) {
                        graph.removeEdge(new StringEdge(srcName, dstName));
                        graph.removeEdge(new StringEdge(dstName, srcName));
                        calculateShortestPath(graph);
                        //log.info("current calculated graph {}", graph);
                        log.info("current calculated flowTables {}", flowTables);
                        updateFlowTables(flowTables);
                        //log.info("current updated flowTables {}", flowTables);
                    }
                } else if (event.type() == LinkEvent.Type.LINK_ADDED) {
                    log.info("LINK_ADDED");
                    if (linkInfo.updateSrcStatus(srcName, dstName, LINK_UP)) {
                        graph.addEdge(new StringEdge(srcName, dstName));
                        graph.addEdge(new StringEdge(dstName, srcName));
                        calculateShortestPath(graph);
                        //log.info("current calculated graph {}", graph);
                        log.info("current calculated flowTables {}", flowTables);
                        updateFlowTables(flowTables);
                        //log.info("current updated flowTables {}", flowTables);
                    }
                } else if (event.type() == LinkEvent.Type.LINK_UPDATED) {
                    log.info("LINK_UPDATED");
                }
            } catch (JSONException e) {
                e.printStackTrace();
            }
        }
    }

    private class EqualEdgeWeight implements EdgeWeight<StringVertex, StringEdge> {
        @Override
        public double weight(StringEdge edge) {
            return 1;
        }
    }

    public static AbstractGraphPathSearch<StringVertex, StringEdge> graphSearch() {
        return new DijkstraGraphSearch<>();
    }

    private void calculateShortestPath(Graph<StringVertex, StringEdge> graph) {
        log.info("calculateShortestPath, current link num {}", graph.getEdges().size());
        int current = 0;
        Iterator<String> hostsKeys1 = hosts.keys();
        while (hostsKeys1.hasNext()) {
            String hostName1 = (String) hostsKeys1.next();
            Iterator<String> hostsKeys2 = hosts.keys();
            while (hostsKeys2.hasNext()) {
                String hostName2 = (String) hostsKeys2.next();
                if (hostName1 == hostName2) {
                    continue;
                }
                StringVertex vertex1 = new StringVertex(hostName1);
                StringVertex vertex2 = new StringVertex(hostName2);
                GraphPathSearch.Result<StringVertex, StringEdge> result =
                        graphSearch().search(graph, vertex1, vertex2, equalWeight, ALL_PATHS);
                if (result.paths().size() == 0) {
                    continue;
                }
                int index = current % result.paths().size();
                current += 1;
                int i = 0;
                List<StringEdge> edges = null;
                for (Path<StringVertex, StringEdge> path : result.paths()) {
                    if (i == index) {
                        edges = path.edges();
                        break;
                    } else {
                        i += 1;
                    }
                }
                if (edges == null) {
                    continue;
                }
                log.info("valid path: {}", edges);
                i = 1;
                while (i < edges.size()) {
                    StringEdge edge = edges.get(i);
                    String srcSW = edge.src().value();
                    String dstSW = edge.dst().value();
                    PortNumber outPort = linkInfo.getOutPort(srcSW, dstSW);
                    flowTables.addFlowEntry(srcSW, hostName1, hostName2, outPort);
                    i += 1;
                }
            }
        }
    }

    private void updateFlowTables(NetFlowEntries netFlowEntries) {
        Iterator<String> swItr = netFlowEntries.netFlowEntriesHashMap.keySet().iterator();
        int updatedFlowEntriesSize = 0;
        int totalUpdatedFlowEntriesSize = 0;
        while (swItr.hasNext()) {
            String swName = swItr.next();
            updatedFlowEntriesSize = 0;
            HashMap switchFlowEntries = (HashMap) netFlowEntries.netFlowEntriesHashMap.get(swName);
            Iterator<Map.Entry<SrcDstPair, StatusFlowEntry>> iter = switchFlowEntries.entrySet().iterator();
            while (iter.hasNext()) {
                Map.Entry<SrcDstPair, StatusFlowEntry> entry = iter.next();
                SrcDstPair pair = entry.getKey();
                StatusFlowEntry statusFlowEntry = entry.getValue();
                try {
                    String swDpid = (String) switchesNameToDpid.get(swName);
                    DeviceId deviceId = DeviceId.deviceId(swDpid);
                    if (deviceService.isAvailable(deviceId)) {
                        if (statusFlowEntry.status == FLOWENTRY_UPDATED) {
                            updatedFlowEntriesSize += 1;
                            installRule(pair, statusFlowEntry.outPort, deviceId);
                            statusFlowEntry.status = FLOWENTRY_DELETED;
                        } else if (statusFlowEntry.status == FLOWENTRY_UPDATED_AND_DELETED) {
                            //deleteRule(pair, statusFlowEntry.oldOutPort, deviceId);
                            updatedFlowEntriesSize += 1;
                            installRule(pair, statusFlowEntry.outPort, deviceId);
                            statusFlowEntry.status = FLOWENTRY_DELETED;
                        } else if (statusFlowEntry.status == FLOWENTRY_DELETED) {
                            updatedFlowEntriesSize += 1;
                            deleteRule(pair, statusFlowEntry.outPort, deviceId);
                            iter.remove();
                        } else if (statusFlowEntry.status == FLOWENTRY_CHECKED) {
                            statusFlowEntry.status = FLOWENTRY_DELETED;
                        } else if (statusFlowEntry.status == FLOWENTRY_WAITING) {
                            iter.remove();
                        }
                    } else {
                        log.info("device {} is not available, update {} rejected", swName, pair);
                        statusFlowEntry.outPort = PortNumber.portNumber(-1);
                        statusFlowEntry.status = FLOWENTRY_WAITING;
                    }
                } catch (JSONException e) {
                    e.printStackTrace();
                }
            }
            log.info("switch: {}, updatedFlowEntriesSize: {}", swName, updatedFlowEntriesSize);
            totalUpdatedFlowEntriesSize += updatedFlowEntriesSize;
        }
        log.info("totalUpdatedFlowEntriesSize: {}", totalUpdatedFlowEntriesSize);
    }

    private final class StatusFlowEntry {
        PortNumber outPort;
        PortNumber oldOutPort;
        int status;

        private StatusFlowEntry(PortNumber outPort) {
            this.outPort = outPort;
            this.oldOutPort = PortNumber.portNumber(-1);
            this.status = FLOWENTRY_WAITING;
        }

        private StatusFlowEntry(PortNumber outPort, int status) {
            this.outPort = outPort;
            this.oldOutPort = PortNumber.portNumber(-1);
            this.status = status;
        }

        @Override
        public String toString() {
            return toStringHelper(this)
                .add("outPort", outPort)
                .add("oldOutPort", oldOutPort)
                .add("status", status)
                .toString();
        }
    }

    private class NetFlowEntries {
        final HashMap netFlowEntriesHashMap;

        private NetFlowEntries() {
            this.netFlowEntriesHashMap = new HashMap();
        }

        public void addSwitch(String sw) {
            if (!netFlowEntriesHashMap.containsKey(sw)) {
                HashMap switchFlowEntries = new HashMap();
                netFlowEntriesHashMap.put(sw, switchFlowEntries);
            }
        }

        public void addFlowEntry(String sw, String srcHost, String dstHost, PortNumber outPort) {
            //log.info("update FlowEntry for {}, host1 {}, host2 {}, port {}", sw, srcHost, dstHost, outPort);
            if (!netFlowEntriesHashMap.containsKey(sw)) {
                HashMap switchFlowEntries = new HashMap();
                netFlowEntriesHashMap.put(sw, switchFlowEntries);
            }
            HashMap switchFlowEntries = (HashMap) netFlowEntriesHashMap.get(sw);
            try {
                String srcAddr = (String) hosts.get(srcHost);
                String dstAddr = (String) hosts.get(dstHost);
                SrcDstPair pair = new SrcDstPair(srcAddr, dstAddr);
                if (!switchFlowEntries.containsKey(pair)) {
                    StatusFlowEntry statusFlowEntry = new StatusFlowEntry(outPort, FLOWENTRY_UPDATED);
                    //log.info("FLOWENTRY_UPDATED");
                    switchFlowEntries.put(pair, statusFlowEntry);
                } else {
                    StatusFlowEntry statusFlowEntry = (StatusFlowEntry) switchFlowEntries.get(pair);
                    if (statusFlowEntry.status == FLOWENTRY_WAITING) {
                        //log.info("FLOWENTRY_UPDATED for FLOWENTRY_WAITING");
                        statusFlowEntry.outPort = outPort;
                        statusFlowEntry.status = FLOWENTRY_UPDATED;
                    } else if (statusFlowEntry.outPort == outPort) {
                        //log.info("FLOWENTRY_CHECKED");
                        statusFlowEntry.status = FLOWENTRY_CHECKED;
                    } else {
                        //log.info("FLOWENTRY_UPDATED_AND_DELETED");
                        statusFlowEntry.status = FLOWENTRY_UPDATED_AND_DELETED;
                        statusFlowEntry.oldOutPort = statusFlowEntry.outPort;
                        statusFlowEntry.outPort = outPort;
                    }
                }
            } catch (JSONException e) {
                e.printStackTrace();
            }
        }

        public HashMap getSwitchFlowEntries(String sw) {
            if (!netFlowEntriesHashMap.containsKey(sw)) {
                return null;
            } else {
                return (HashMap) netFlowEntriesHashMap.get(sw);
            }
        }

        @Override
        public String toString() {
            ToStringHelper ret = toStringHelper(this);
            Iterator<String> swItr = netFlowEntriesHashMap.keySet().iterator();
            while (swItr.hasNext()) {
                String swName = swItr.next();
                ret.add("\nsw_name", swName);
                HashMap switchFlowEntries = (HashMap) netFlowEntriesHashMap.get(swName);
                ret.add("entrysize", switchFlowEntries.size());
                Iterator<SrcDstPair> srcdstItr = switchFlowEntries.keySet().iterator();
                while (srcdstItr.hasNext()) {
                    SrcDstPair pair = srcdstItr.next();
                    ret.add("link", pair);
                    StatusFlowEntry statusFlowEntry = (StatusFlowEntry) switchFlowEntries.get(pair);
                    ret.add("entry", statusFlowEntry);
                }
            }
            return ret.toString();
        }
    }

    private void installRule(SrcDstPair pair, PortNumber portNo, DeviceId deviceId) {
        //log.info("Installing flow rules to: {} by flowRuleService", deviceId);
        TrafficSelector.Builder selectorBuilder = DefaultTrafficSelector.builder();

        selectorBuilder.matchEthType(Ethernet.TYPE_IPV4)
                .matchIPSrc(pair.src)
                .matchIPDst(pair.dst);

        TrafficTreatment treatment = DefaultTrafficTreatment.builder()
                .setOutput(portNo)
                .build();

        FlowRule flowRule = DefaultFlowRule.builder()
                .withSelector(selectorBuilder.build())
                .withTreatment(treatment)
                .withPriority(DEFAULT_PRIORITY)
                .fromApp(appId)
                .forDevice(deviceId)
                .makePermanent()
                .build();

        flowRuleService.applyFlowRules(flowRule);
    }


    private void deleteRule(SrcDstPair pair, PortNumber portNo, DeviceId deviceId) {
        //log.info("remove flow rule from: {} by flowRuleService", deviceId);
        TrafficSelector.Builder selectorBuilder = DefaultTrafficSelector.builder();

        selectorBuilder.matchEthType(Ethernet.TYPE_IPV4)
                .matchIPSrc(pair.src)
                .matchIPDst(pair.dst);

        TrafficTreatment treatment = DefaultTrafficTreatment.builder()
                .setOutput(portNo)
                .build();

        FlowRule flowRule = DefaultFlowRule.builder()
                .withSelector(selectorBuilder.build())
                .withTreatment(treatment)
                .withPriority(DEFAULT_PRIORITY)
                .fromApp(appId)
                .forDevice(deviceId)
                .makePermanent()
                .build();

        flowRuleService.removeFlowRules(flowRule);
    }

    // Wrapper class for a source and destination pair of IP Prefix
    private final class SrcDstPair {
        final Ip4Prefix src;
        final Ip4Prefix dst;

        private SrcDstPair(Ip4Prefix src, Ip4Prefix dst) {
            this.src = src;
            this.dst = dst;
        }

        private SrcDstPair(String src, String dst) {
            this.src = Ip4Prefix.valueOf(src + "/32");
            this.dst = Ip4Prefix.valueOf(dst + "/32");
        }


        @Override
        public boolean equals(Object o) {
            if (this == o) {
                return true;
            }
            if (o == null || getClass() != o.getClass()) {
                return false;
            }
            SrcDstPair that = (SrcDstPair) o;
            return Objects.equals(src, that.src) &&
                    Objects.equals(dst, that.dst);
        }

        @Override
        public int hashCode() {
            return Objects.hash(src, dst);
        }

        @Override
        public String toString() {
            return toStringHelper(this)
                .add("src", src)
                .add("dst", dst)
                .toString();
        }
    }

    private final class StringVertex implements Vertex {
        final String name;

        private StringVertex(String name) {
            this.name = name;
        }

        @Override
        public boolean equals(Object o) {
            if (this == o) {
                return true;
            }
            if (o == null || getClass() != o.getClass()) {
                return false;
            }
            StringVertex that = (StringVertex) o;
            return Objects.equals(name, that.name);
        }

        @Override
        public int hashCode() {
            return Objects.hash(name);
        }

        public String value() {
            return name;
        }

        @Override
        public String toString() {
            return name;
        }
    }

    // directed
    private final class StringEdge implements Edge<StringVertex> {
        final StringVertex srcVertex;
        final StringVertex dstVertex;

        private StringEdge(StringVertex srcVertex, StringVertex dstVertex) {
            this.srcVertex = srcVertex;
            this.dstVertex = dstVertex;
        }

        private StringEdge(String src, String dst) {
            this.srcVertex = new StringVertex(src);
            this.dstVertex = new StringVertex(dst);
        }

        @Override
        public StringVertex dst() {
            return dstVertex;
        }

        @Override
        public StringVertex src() {
            return srcVertex;
        }

        @Override
        public boolean equals(Object o) {
            if (this == o) {
                return true;
            }
            if (o == null || getClass() != o.getClass()) {
                return false;
            }
            StringEdge that = (StringEdge) o;
            return Objects.equals(srcVertex, that.srcVertex) &&
                    Objects.equals(dstVertex, that.dstVertex);
        }

        @Override
        public int hashCode() {
            return Objects.hash(srcVertex, dstVertex);
        }

        @Override
        public String toString() {
            return srcVertex.toString() + "<-->" + dstVertex.toString();
        }
    }

    private final class LinkTuple {
        final String sw1;
        final String sw2;
        final PortNumber portNo1;
        final PortNumber portNo2;
        int status1;
        int status2;

        private LinkTuple(String sw1, String sw2, PortNumber portNo1, PortNumber portNo2) {
            this.sw1 = sw1;
            this.sw2 = sw2;
            this.portNo1 = portNo1;
            this.portNo2 = portNo2;
            this.status1 = LINK_DOWN;
            this.status2 = LINK_DOWN;
        }

        private LinkTuple(String sw1, String sw2, PortNumber portNo1, PortNumber portNo2, int status1, int status2) {
            this.sw1 = sw1;
            this.sw2 = sw2;
            this.portNo1 = portNo1;
            this.portNo2 = portNo2;
            this.status1 = status1;
            this.status2 = status2;
        }

        @Override
        public String toString() {
            return toStringHelper(this)
                .add("s1", sw1)
                .add("s2", sw2)
                .add("status1", status1)
                .add("status2", status2)
                .toString();
        }
    }

    private final class LinkInfo {
        final HashMap hashMap;

        private LinkInfo() {
            this.hashMap = new HashMap();
        }

        public void loadLink(String sw1, String sw2, long portNo1, long portNo2) {
            if (sw1.compareTo(sw2) <= 0) {
                String key = sw1 + sw2;
                LinkTuple linkTuple
                    = new LinkTuple(sw1, sw2, PortNumber.portNumber(portNo1), PortNumber.portNumber(portNo2));
                hashMap.put(key, linkTuple);
            } else {
                String key = sw2 + sw1;
                LinkTuple linkTuple
                    = new LinkTuple(sw2, sw1, PortNumber.portNumber(portNo2), PortNumber.portNumber(portNo1));
                hashMap.put(key, linkTuple);
            }
        }

        // update directed link status, the status is for sw1
        // return true if one end of the link is down, or both ends of the link are up
        public boolean updateSrcStatus(String sw1, String sw2, int status) {
            String key = sw1 + sw2;
            if (sw1.compareTo(sw2) > 0) {
                key = sw2 + sw1;
            }
            LinkTuple linkTuple = (LinkTuple) hashMap.get(key);
            if (sw1.equals(linkTuple.sw1) && status == linkTuple.status1) {
                return false;
            } else if (sw1.equals(linkTuple.sw1) && status == LINK_DOWN) {
                linkTuple.status1 = status;
                if (linkTuple.status2 == LINK_DOWN) {
                    return false;
                } else {
                    return true;
                }
            } else if (sw1.equals(linkTuple.sw1) && status == LINK_UP) {
                linkTuple.status1 = status;
                if (linkTuple.status2 == LINK_DOWN) {
                    return false;
                } else {
                    return true;
                }
            } else if (sw1.equals(linkTuple.sw2) && status == linkTuple.status2) {
                return false;
            } else if (sw1.equals(linkTuple.sw2) && status == LINK_DOWN) {
                linkTuple.status2 = status;
                if (linkTuple.status1 == LINK_DOWN) {
                    return false;
                } else {
                    return true;
                }
            } else {
                linkTuple.status2 = status;
                if (linkTuple.status1 == LINK_DOWN) {
                    return false;
                } else {
                    return true;
                }
            }
        }

        // return the portNo of sw1, sw1 --> sw2
        public PortNumber getOutPort(String sw1, String sw2) {
            if (sw1.compareTo(sw2) <= 0) {
                String key = sw1 + sw2;
                LinkTuple linkTuple = (LinkTuple) hashMap.get(key);
                return linkTuple.portNo1;
            } else {
                String key = sw2 + sw1;
                LinkTuple linkTuple = (LinkTuple) hashMap.get(key);
                return linkTuple.portNo2;
            }
        }
    }
}
