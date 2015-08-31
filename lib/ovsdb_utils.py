import json
import socket
from conf.const import RECV_BUF_SIZE

# ovsdb json rpc
bridge_query = {
    "method": "transact",
    "params": [
        "Open_vSwitch",
        {
            "op": "select",
            "table": "Bridge",
            "where": [
                [
                    "datapath_id",
                    "==",
                    ""
                ]
            ],
            "columns": [
                "ports"
            ]
        }
    ],
    "id": 0
}

port_query = {
    "method": "transact",
    "params": [
        "Open_vSwitch",
        {
            "op": "select",
            "table": "Port",
            "where": [
                [
                    "_uuid",
                    "==",
                    [
                        "uuid",
                        ""
                    ]
                ]
            ],
            "columns": [
                "interfaces"
            ]
        }
    ],
    "id": 0
}

interface_query = {
    "method": "transact",
    "params": [
        "Open_vSwitch",
        {
            "op": "select",
            "table": "Interface",
            "where": [
                [
                    "type",
                    "!=",
                    "internal"
                ], [
                    "_uuid",
                    "==",
                    [
                        "uuid",
                        ""
                    ]
                ]
            ],
            "columns": [
                "name",
                "link_state"
            ]
        }
    ],
    "id": 0
}


class OvsdbConn(object):
    def __init__(self, ovsdb_path):
        self.path = ovsdb_path
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self.path)
        self.datapath_id = '0000000000000000'
        self.port_ids = []
        self.intf_ids = []
        self.link_states = {}

    def query(self):
        # TODO: check all conditions (set or single, keyerror)
        bridge_query["params"][1]["where"][0][2] = self.datapath_id
        self.sock.send(json.dumps(bridge_query))
        response = self.sock.recv(RECV_BUF_SIZE)
        try:
            self.port_ids = json.loads(response)['result'][0]['rows']\
                                                [0]['ports'][1]
        except:
            return {}
        for port_id in self.port_ids:
            port_query["params"][1]["where"][0][2][1] = port_id[1]
            self.sock.send(json.dumps(port_query))
            response = self.sock.recv(RECV_BUF_SIZE)
            try:
                intf_id = json.loads(response)['result'][0]['rows']\
                                              [0]['interfaces'][1]
                self.intf_ids.append(intf_id)
            except:
                return {}
            interface_query["params"][1]["where"][1][2][1] = intf_id
            self.sock.send(json.dumps(interface_query))
            response = self.sock.recv(RECV_BUF_SIZE)
            result = json.loads(response)['result'][0]['rows']
            if result:
                self.link_states[result[0]['name']] =\
                        0 if result[0]['link_state'] == 'up' else 1
        return self.link_states


if __name__ == "__main__":
    ovsdb_conn = OvsdbConn('/var/run/openvswitch/db.sock')
    ovsdb_conn.datapath_id = '0000000000000002'
    ovsdb_conn.query()
