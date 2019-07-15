# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#

import cyclecloud.api.clusters
from cyclecloud.model.NodeManagementRequestModule import NodeManagementRequest
from slurmcc import chaos_mode


class ClusterWrapper:
    
    def __init__(self, cluster_name, session=None, client=None, clusters_module=None):
        self.cluster_name = cluster_name
        self.session = session or self.cluster._client._session
        self.client = client or self.cluster._client
        self.clusters_module = clusters_module or cyclecloud.api.clusters
    
    @chaos_mode
    def get_cluster_status(self, nodes=False):
        return self.clusters_module.get_cluster_status(self.session, self.cluster_name, nodes)
    
    @chaos_mode
    def get_nodes(self, operation_id=None, request_id=None):
        return self.clusters_module.get_nodes(self.session, self.cluster_name, operation_id, request_id)
    
    @chaos_mode
    def scale(self, nodearray, total_core_count=None, total_node_count=None):
        return self.clusters_module.scale(self.session, self.cluster_name, nodearray, total_core_count, total_node_count)
    
    @chaos_mode
    def remove_nodes(self, names=None, node_ids=None, hostnames=None, ip_addresses=None, custom_filter=None):
        request = self._node_management_request(names, node_ids, hostnames, ip_addresses, custom_filter)
        return self.clusters_module.remove_nodes(self.session, self.cluster_name, request)
    
    @chaos_mode
    def deallocate_nodes(self, names=None, node_ids=None, hostnames=None, ip_addresses=None, custom_filter=None):
        request = self._node_management_request(names, node_ids, hostnames, ip_addresses, custom_filter)
        return self.clusters_module.deallocate_nodes(self.session, self.cluster_name, request)
    
    @chaos_mode
    def shutdown_nodes(self, names=None, node_ids=None, hostnames=None, ip_addresses=None, custom_filter=None):
        request = self._node_management_request(names, node_ids, hostnames, ip_addresses, custom_filter)
        return self.clusters_module.shutdown_nodes(self.session, self.cluster_name, request)
    
    @chaos_mode
    def start_nodes(self, names=None, node_ids=None, hostnames=None, ip_addresses=None, custom_filter=None):
        request = self._node_management_request(names, node_ids, hostnames, ip_addresses, custom_filter)
        return self.clusters_module.start_nodes(self.session, self.cluster_name, request)
    
    @chaos_mode
    def create_nodes(self, node_creation_request):
        node_creation_request.validate()
        return self.clusters_module.create_nodes(self.session, self.cluster_name, node_creation_request)
    
    @chaos_mode
    def terminate_nodes(self, names=None, node_ids=None, hostnames=None, ip_addresses=None, custom_filter=None):
        request = self._node_management_request(names, node_ids, hostnames, ip_addresses, custom_filter)
        return self.clusters_module.terminate_nodes(self.session, self.cluster_name, request)
    
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
            request.filter = custom_filter
            
        request.validate()
        
        return request
