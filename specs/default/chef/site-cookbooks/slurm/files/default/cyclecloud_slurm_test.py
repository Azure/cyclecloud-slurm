# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#

import cStringIO
from collections import OrderedDict
import logging
import unittest

import clusterwrapper
from cyclecloud.model.ClusterNodearrayStatusModule import ClusterNodearrayStatus
from cyclecloud.model.ClusterStatusModule import ClusterStatus
from cyclecloud.model.NodeListModule import NodeList
from cyclecloud.model.NodeManagementResultModule import NodeManagementResult
from cyclecloud.model.NodearrayBucketStatusDefinitionModule import NodearrayBucketStatusDefinition
from cyclecloud.model.NodearrayBucketStatusModule import NodearrayBucketStatus
from cyclecloud.model.NodearrayBucketStatusVirtualMachineModule import NodearrayBucketStatusVirtualMachine
from cyclecloud_slurm import Partition, ExistingNodePolicy, CyclecloudSlurmError
import cyclecloud_slurm
from cyclecloud.model.NodeCreationResultModule import NodeCreationResult
from cyclecloud.model.NodeCreationResultSetModule import NodeCreationResultSet


logging.basicConfig(level=logging.DEBUG, format="%(message)s")


class DoNotUse:
    
    def __getattribute__(self, key):
        raise RuntimeError()
    
    
class MockClusterModule:
    def __init__(self):
        self.cluster_status_response = None
        self.expected_create_nodes_request = None
        self.expected_start_nodes_request = None
        self.name = "mock-cluster"
        # modify this to set get_nodes() response
        self._started_nodes = []
        
    def get_cluster_status(self, session, cluster_name, nodes):
        assert isinstance(session, DoNotUse)
        assert cluster_name == self.name
        
        # TODO
        return None, self.cluster_status_response
    
    def create_nodes(self, session, cluster_name, request):
        assert isinstance(session, DoNotUse)
        assert cluster_name == self.name
        if self.expected_create_nodes_request["sets"] != request.to_dict()["sets"]:
            for e, a in zip(self.expected_create_nodes_request["sets"], request.to_dict()["sets"]):
                assert set(e.keys()) == set(a.keys()), "%s or %s at %s" % (set(e.keys()) - set(a.keys()), set(a.keys()) - set(e.keys()), e)
                for k in e:
                    if e[k] != a[k]:
                        raise AssertionError("%s != %s for key %s" % (e[k], a[k], k))
                    
        assert self.expected_create_nodes_request["sets"] == request.to_dict()["sets"], "\n%s\n%s" % (self.expected_create_nodes_request["sets"], request.to_dict()["sets"])
        
        # for now just assume each request was a success
        resp = NodeCreationResult()
        resp.sets = []
        for request_set in request.sets:
            ncr = NodeCreationResultSet()
            ncr.added = request_set.count
            resp.sets.append(ncr)
        return None, resp
    
    def start_nodes(self, session, cluster_name, request):
        assert isinstance(session, DoNotUse)
        assert cluster_name == self.name
        assert self.expected_start_nodes_request == request.to_dict(), "%s\n != %s" % (self.expected_start_nodes_request, request.to_dict())
        self._started_nodes = []
        for n, name in enumerate(request.names):
            self._started_nodes.append({"Name": name, "TargetState": "Started", "State": "Started", "PrivateIp": "10.1.0.%d" % n})
        result = NodeManagementResult()
        result.operation_id = "start_nodes-operation-id"
        return None, result
    
    def get_nodes(self, session, cluster_name, operation_id, request_id):
        node_list = NodeList()
        node_list.nodes = self._started_nodes
        return None, node_list
    

class MockSubprocessModule:
    def __init__(self):
        self._expectations = []
        
    def expect(self, args, response=None):
        if isinstance(args, basestring):
            args = args.split()
            
        self._expectations.append((args, response))
        
    def check_output(self, args):
        assert self._expectations, "unexpected subprocess call - %s" % args
        expected_args, response = self._expectations.pop(0)
        assert expected_args == args, "%s != %s" % (expected_args, args)
        return response
    
    def check_call(self, args):
        expected_args, _ = self._expectations.pop(0)
        assert expected_args == args, "%s != %s" % (expected_args, args)
        
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        if not args[1]:
            assert len(self._expectations) == 0
    

class CycleCloudSlurmTest(unittest.TestCase):
    
    def test_fetch_partitions(self):
        mock_cluster = MockClusterModule()
        
        with MockSubprocessModule() as mock_subprocess:
            # big long setup to create two nodearrays, hpc and htc, similar to what we have in the default
            # template
            
            cluster_status = ClusterStatus()
            mock_cluster.cluster_status_response = cluster_status
            
            cluster_status.nodes = []
            hpc_nodearray_status = ClusterNodearrayStatus()
            hpc_nodearray_status.name = "hpc"
            htc_nodearray_status = ClusterNodearrayStatus()
            htc_nodearray_status.name = "htc"
            cluster_status.nodearrays = [hpc_nodearray_status, htc_nodearray_status]
            
            bucket = NodearrayBucketStatus()
            hpc_nodearray_status.buckets = [bucket]
            htc_nodearray_status.buckets = [bucket]
            
            bucket.max_count = 2
            
            bucket.definition = NodearrayBucketStatusDefinition()
            bucket.definition.machine_type = "Standard_D2_v2"
            
            # hpc is default htc has hpc==false
            hpc_nodearray_status.nodearray = {"MachineType": bucket.definition.machine_type,
                                              "Azure": {"MaxScalesetSize": 30},
                                          "Configuration": {"slurm": {"autoscale": True, "default_partition": True}}}
            htc_nodearray_status.nodearray = {"MachineType": bucket.definition.machine_type,
                                          "Configuration": {"slurm": {"autoscale": True, "hpc": False}}}
            
            vm = NodearrayBucketStatusVirtualMachine()
            vm.memory = 4
            vm.vcpu_count = 2
            bucket.virtual_machine = vm
            
            # based on the cluster status above, fetch partitions 
            cluster_wrapper = clusterwrapper.ClusterWrapper(mock_cluster.name, DoNotUse(), DoNotUse(), mock_cluster)
            partitions = cyclecloud_slurm.fetch_partitions(cluster_wrapper, mock_subprocess)
            self.assertEquals(2, len(partitions))
            hpc_part = partitions["hpc"]
            
            self.assertEquals("hpc", hpc_part.name)
            self.assertEquals("hpc", hpc_part.nodearray)
            self.assertEquals(None, hpc_part.node_list)
            self.assertTrue(hpc_part.is_default)
            self.assertTrue(hpc_part.is_hpc)
            
            htc_part = partitions["htc"]
            self.assertEquals("htc", htc_part.name)
            self.assertEquals("htc", htc_part.nodearray)
            self.assertEquals(None, htc_part.node_list)
            self.assertFalse(htc_part.is_default)
            self.assertFalse(htc_part.is_hpc)
            
            self.assertEquals(bucket.definition.machine_type, hpc_part.machine_type)
            self.assertEquals(30, hpc_part.max_scaleset_size)
            self.assertEquals(2, hpc_part.max_vm_count)
            self.assertEquals(4, hpc_part.memory)
            self.assertEquals(2, hpc_part.vcpu_count)
            
            self.assertEquals(bucket.definition.machine_type, htc_part.machine_type)
            self.assertEquals(2**31, htc_part.max_scaleset_size)
            self.assertEquals(2, htc_part.max_vm_count)
            self.assertEquals(4, htc_part.memory)
            self.assertEquals(2, htc_part.vcpu_count)
            
            mock_cluster._started_nodes = [{"Name": "hpc-100", "Template": "hpc"},
                                            {"Name": "hpc-101", "Template": "hpc"},
                                            {"Name": "hpc-102", "Template": "hpc"}]
            
            # now there are pre-existing nodes, so just use those to determine the node_list
            mock_subprocess.expect("scontrol show hostlist hpc-100,hpc-101,hpc-102", "hpc-10[0-2]")
            partitions = cyclecloud_slurm.fetch_partitions(cluster_wrapper, mock_subprocess)
            self.assertEquals("hpc-10[0-2]", partitions["hpc"].node_list)
            
            # change max scale set size
            mock_subprocess.expect("scontrol show hostlist hpc-100,hpc-101,hpc-102", "hpc-10[0-2]")
            hpc_nodearray_status.nodearray["Azure"] = {"MaxScalesetSize": 2}
            partitions = cyclecloud_slurm.fetch_partitions(cluster_wrapper, mock_subprocess)
            self.assertEquals("hpc-10[0-2]", partitions["hpc"].node_list)
            self.assertEquals(2, partitions["hpc"].max_scaleset_size)
            
            # ensure we can disable autoscale
            hpc_nodearray_status.nodearray["Configuration"]["slurm"]["autoscale"] = False
            htc_nodearray_status.nodearray["Configuration"]["slurm"]["autoscale"] = False
            partitions = cyclecloud_slurm.fetch_partitions(cluster_wrapper, mock_subprocess)
            self.assertEquals(0, len(partitions))
            
            # default for autoscale is false
            hpc_nodearray_status.nodearray["Configuration"]["slurm"].pop("autoscale")
            htc_nodearray_status.nodearray["Configuration"]["slurm"].pop("autoscale")
            partitions = cyclecloud_slurm.fetch_partitions(cluster_wrapper, mock_subprocess)
            self.assertEquals(0, len(partitions))
            
    def test_create_nodes(self):
        partitions = {}
        partitions["hpc"] = Partition("hpc", "hpc", "Standard_D2_v2", is_default=True, is_hpc=True, max_scaleset_size=3, vcpu_count=2, memory=4, max_vm_count=8)
        partitions["htc"] = Partition("htc", "htc", "Standard_D2_v2", is_default=False, is_hpc=False, max_scaleset_size=100, vcpu_count=2, memory=4, max_vm_count=8)
        
        mock_cluster = MockClusterModule()
        cluster_wrapper = clusterwrapper.ClusterWrapper(mock_cluster.name, DoNotUse(), DoNotUse(), mock_cluster)
        subprocess_module = MockSubprocessModule()
        # create 3 placement groups for hpc with sizes 3,3,2 (3 + 3 + 2 = 8, which is the max_vm_count_
        # al
        expected_request = {'sets': [
            {'count': 3,
             'nameFormat': 'hpc-pg0-%d',
             'nameOffset': 1,
             'definition': {'machineType': 'Standard_D2_v2'},
             'nodeAttributes': {'StartAutomatically': False,
                                'Fixed': True},
             'nodearray': 'hpc',
             'placementGroupId': 'hpc-Standard_D2_v2-pg0'},
            {'count': 3,
             'nameFormat': 'hpc-pg1-%d',
             'nameOffset': 1,
             'definition': {'machineType': 'Standard_D2_v2'},
             'nodeAttributes': {'StartAutomatically': False,
                                'Fixed': True},
             'nodearray': 'hpc',
             'placementGroupId': 'hpc-Standard_D2_v2-pg1'},
            {'count': 2,
             'nameFormat': 'hpc-pg2-%d',
             'nameOffset': 1,
             'definition': {'machineType': 'Standard_D2_v2'},
             'nodeAttributes': {'StartAutomatically': False,
                                'Fixed': True},
             'nodearray': 'hpc',
             'placementGroupId': 'hpc-Standard_D2_v2-pg2'},
            {'count': 8,
             'nameFormat': 'htc-%d',
             'nameOffset': 1,
             'definition': {'machineType': 'Standard_D2_v2'},
             'nodeAttributes': {'StartAutomatically': False,
                                'Fixed': True},
             'nodearray': 'htc'}]}
        mock_cluster.expected_create_nodes_request = expected_request
        cyclecloud_slurm._create_nodes(partitions, cluster_wrapper, subprocess_module)
        
        # ok now bump max vm count 1 and try recreating.
        partitions["hpc"].max_vm_count += 1
        partitions["hpc"].node_list = "hpc-pg0-[1-3],hpc-pg1-[1-3],hpc-pg2-[1-2]"
        
        for _ in range(3):
            subprocess_module.expect(['scontrol', 'show', 'hostnames', 'hpc-pg0-[1-3],hpc-pg1-[1-3],hpc-pg2-[1-2]'], 
                                     " ".join(["hpc-pg0-1", "hpc-pg0-2", "hpc-pg0-3", "hpc-pg1-1", "hpc-pg1-2", "hpc-pg1-3", "hpc-pg2-1", "hpc-pg2-2"]))
        
        # fails because existing node policy is default, error
        self.assertRaises(CyclecloudSlurmError, lambda: cyclecloud_slurm._create_nodes(partitions, cluster_wrapper, subprocess_module, existing_policy=ExistingNodePolicy.Error))
        
        # succeeds because existing node policy is AllowExisting, so we fill in / add nodes
        
        expected_request["sets"] = [{'count': 1,
             'nameFormat': 'hpc-pg2-%d',
             'nameOffset': 3,
             'definition': {'machineType': 'Standard_D2_v2'},
             'nodeAttributes': {'StartAutomatically': False,
                                'Fixed': True},
             'nodearray': 'hpc',
             'placementGroupId': 'hpc-Standard_D2_v2-pg2'},
             {'count': 8,
             'nameFormat': 'htc-%d',
             'nameOffset': 1,
             'definition': {'machineType': 'Standard_D2_v2'},
             'nodeAttributes': {'StartAutomatically': False,
                                'Fixed': True},
             'nodearray': 'htc'}]
        cyclecloud_slurm._create_nodes(partitions, cluster_wrapper, subprocess_module, existing_policy=ExistingNodePolicy.AllowExisting)
        
    def test_generate_slurm_conf(self):
        writer = cStringIO.StringIO()
        partitions = OrderedDict()
        partitions["hpc"] = Partition("custom_partition_name", "hpc", "Standard_D2_v2", is_default=True, is_hpc=True, max_scaleset_size=3, vcpu_count=2, memory=4, max_vm_count=8)
        partitions["htc"] = Partition("htc", "htc", "Standard_D2_v3", is_default=False, max_scaleset_size=100, is_hpc=False, vcpu_count=2, memory=3.5, max_vm_count=8)

        partitions["hpc"].node_list = "hpc-10[1-8]"
        partitions["htc"].node_list = "htc-[1-8]"
        with MockSubprocessModule() as mock_subprocess:
            mock_subprocess.expect(['scontrol', 'show', 'hostnames', 'hpc-10[1-8]'], "hpc-101 hpc-102 hpc-103 hpc-104 hpc-105 hpc-106 hpc-107 hpc-108")
            mock_subprocess.expect(['scontrol', 'show', 'hostlist', "hpc-101,hpc-102,hpc-103"], 'hpc-10[1-3]')
            mock_subprocess.expect(['scontrol', 'show', 'hostlist', "hpc-104,hpc-105,hpc-106"], 'hpc-10[4-6]')
            mock_subprocess.expect(['scontrol', 'show', 'hostlist', "hpc-107,hpc-108"], 'hpc-10[7-8]')
            mock_subprocess.expect(['scontrol', 'show', 'hostnames', 'htc-[1-8]'], "htc-1 htc-2 htc-3 htc-4 htc-5 htc-6 htc-7 htc-8")
            mock_subprocess.expect(['scontrol', 'show', 'hostlist', "htc-1,htc-2,htc-3,htc-4,htc-5,htc-6,htc-7,htc-8"], 'htc-[1-8]')
            cyclecloud_slurm._generate_slurm_conf(partitions, writer, mock_subprocess)
        result = writer.getvalue().strip()
        expected = '''
PartitionName=custom_partition_name Nodes=hpc-10[1-8] Default=YES MaxTime=INFINITE State=UP
Nodename=hpc-10[1-3] Feature=cloud STATE=CLOUD CPUs=2 RealMemory=4096
Nodename=hpc-10[4-6] Feature=cloud STATE=CLOUD CPUs=2 RealMemory=4096
Nodename=hpc-10[7-8] Feature=cloud STATE=CLOUD CPUs=2 RealMemory=4096
PartitionName=htc Nodes=htc-[1-8] Default=NO MaxTime=INFINITE State=UP
Nodename=htc-[1-8] Feature=cloud STATE=CLOUD CPUs=2 RealMemory=3584'''.strip()
        for e, a in zip(result.splitlines(), expected.splitlines()):
            assert e == a, "\n%s\n%s" % (e, a)
        
    def test_generate_topology(self):
        writer = cStringIO.StringIO()
     
        mock_cluster = MockClusterModule()
        cluster_wrapper = clusterwrapper.ClusterWrapper(mock_cluster.name, DoNotUse(), DoNotUse(), mock_cluster)
        with MockSubprocessModule() as subprocess_module:
            # no nodes, should fail
            self.assertRaises(CyclecloudSlurmError, lambda: cyclecloud_slurm._generate_topology(cluster_wrapper, subprocess_module, writer))
            slurm_conf = {"Configuration": {"slurm": {"autoscale": True}}}
            subprocess_module.expect(['scontrol', 'show', 'hostlist', 'hpc-pg0-1,hpc-pg0-2,hpc-pg0-3'], 'hpc-pg0-[1-3]')
            subprocess_module.expect(['scontrol', 'show', 'hostlist', 'hpc-pg1-1,hpc-pg1-2,hpc-pg1-3'], 'hpc-pg1-[1-3]')
            subprocess_module.expect(['scontrol', 'show', 'hostlist', 'hpc-pg2-1,hpc-pg2-2'], 'hpc-pg2-[1-2]')
            subprocess_module.expect(['scontrol', 'show', 'hostlist', 'htc-1,htc-2,htc-3,htc-4,htc-5,htc-6,htc-7,htc-8'], 'htc-[1-8]')
            
            mock_cluster._started_nodes = [{"Name": "hpc-pg0-1", "PlacementGroupId": "hpc-Standard_D2_v2-pg0"},
                                           {"Name": "hpc-pg0-2", "PlacementGroupId": "hpc-Standard_D2_v2-pg0"},
                                           {"Name": "hpc-pg0-3", "PlacementGroupId": "hpc-Standard_D2_v2-pg0"},
                                           {"Name": "hpc-pg1-1", "PlacementGroupId": "hpc-Standard_D2_v2-pg1"},
                                           {"Name": "hpc-pg1-2", "PlacementGroupId": "hpc-Standard_D2_v2-pg1"},
                                           {"Name": "hpc-pg1-3", "PlacementGroupId": "hpc-Standard_D2_v2-pg1"},
                                           {"Name": "hpc-pg2-1", "PlacementGroupId": "hpc-Standard_D2_v2-pg2"},
                                           {"Name": "hpc-pg2-2", "PlacementGroupId": "hpc-Standard_D2_v2-pg2"},
                                           {"Name": "htc-1"},
                                           {"Name": "htc-2"},
                                           {"Name": "htc-3"},
                                           {"Name": "htc-4"},
                                           {"Name": "htc-5"},
                                           {"Name": "htc-6"},
                                           {"Name": "htc-7"},
                                           {"Name": "htc-8"}]
        
            [x.update(slurm_conf) for x in mock_cluster._started_nodes]
            cyclecloud_slurm._generate_topology(cluster_wrapper, subprocess_module, writer)
            
            result = writer.getvalue().strip()
            expected = '''
SwitchName=hpc-Standard_D2_v2-pg0 Nodes=hpc-pg0-[1-3]
SwitchName=hpc-Standard_D2_v2-pg1 Nodes=hpc-pg1-[1-3]
SwitchName=hpc-Standard_D2_v2-pg2 Nodes=hpc-pg2-[1-2]
SwitchName=htc Nodes=htc-[1-8]'''.strip()
            for e, a in zip(result.splitlines(), expected.splitlines()):
                assert e.strip() == a.strip(), "\n%s\n%s" % (e.strip(), a.strip())        
            
            self.assertEquals(result.strip(), expected.strip())
        
    def test_resume(self):
        mock_cluster = MockClusterModule()
        cluster_wrapper = clusterwrapper.ClusterWrapper(mock_cluster.name, DoNotUse(), DoNotUse(), mock_cluster)
        
        with MockSubprocessModule() as subprocess_module:
            
            subprocess_module.expect("scontrol update NodeName=hpc-1 NodeAddr=10.1.0.0 NodeHostname=10.1.0.0".split())
            mock_cluster.expected_start_nodes_request = {'names': ['hpc-1']}
            cyclecloud_slurm._resume(["hpc-1"], cluster_wrapper, subprocess_module)
            
            subprocess_module.expect("scontrol update NodeName=hpc-1 NodeAddr=10.1.0.0 NodeHostname=10.1.0.0".split())
            subprocess_module.expect("scontrol update NodeName=hpc-44 NodeAddr=10.1.0.1 NodeHostname=10.1.0.1".split())
            mock_cluster.expected_start_nodes_request = {'names': ['hpc-1', 'hpc-44']}
            cyclecloud_slurm._resume(["hpc-1", "hpc-44"], cluster_wrapper, subprocess_module)
