# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#

from cyclecloud.api import clusters
from cyclecloud.model.NodeManagementRequestModule import NodeManagementRequest


class ClusterWrapper:
    
    def __init__(self, cluster, session=None, client=None):
        self.cluster = cluster
        self.session = session or self.cluster._client._session
        self.client = client or self.cluster._client
    
    def get_cluster_status(self, nodes=False):
        return clusters.get_cluster_status(self.session, self.cluster.name, nodes)
    
    def get_nodes(self, operation_id=None, request_id=None):
        return clusters.get_nodes(self.session, self.cluster.name, operation_id, request_id)
    
    def scale(self, nodearray, total_core_count=None, total_node_count=None):
        return clusters.scale(self.session, self.cluster.name, nodearray, total_core_count, total_node_count)

    def remove_nodes(self, names=None, node_ids=None, hostnames=None, ip_addresses=None, custom_filter=None):
        request = self._node_management_request(names, node_ids, hostnames, ip_addresses, custom_filter)
        return clusters.remove_nodes(self.session, self.cluster.name, request)
    
    def deallocate_nodes(self, names=None, node_ids=None, hostnames=None, ip_addresses=None, custom_filter=None):
        request = self._node_management_request(names, node_ids, hostnames, ip_addresses, custom_filter)
        return clusters.deallocate_nodes(self.session, self.cluster.name, request)
    
    def shutdown_nodes(self, names=None, node_ids=None, hostnames=None, ip_addresses=None, custom_filter=None):
        request = self._node_management_request(names, node_ids, hostnames, ip_addresses, custom_filter)
        return clusters.shutdown_nodes(self.session, self.cluster.name, request)
    
    def start_nodes(self, names=None, node_ids=None, hostnames=None, ip_addresses=None, custom_filter=None):
        request = self._node_management_request(names, node_ids, hostnames, ip_addresses, custom_filter)
        return clusters.start_nodes(self.session, self.cluster.name, request)
    
    def create_nodes(self, node_creation_request):
        node_creation_request.validate()
        return clusters.create_nodes(self.session, self.cluster.name, node_creation_request)
    
    def terminate_nodes(self, names=None, node_ids=None, hostnames=None, ip_addresses=None, custom_filter=None):
        request = self._node_management_request(names, node_ids, hostnames, ip_addresses, custom_filter)
        return clusters.terminate_nodes(self.session, self.cluster.name, request)
    
    def _node_management_request(self, names=None, node_ids=None, hostnames=None, ip_addresses=None, custom_filter=None):
        request = NodeManagementRequest()
        if names:
            request.names = names
            
        if node_ids:
            request.ids = node_ids
        
        if hostnames:
            request.hostnames = hostnames
            
        if ip_addresses:
            request.ip_addresses = ip_addresses
            
        if custom_filter:
            request.custom_filter = custom_filter
            
        request.validate()
        
        return request
