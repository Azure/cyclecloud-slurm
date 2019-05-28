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
        self._started_nodes = []
        
    def get_cluster_status(self, session, cluster_name, nodes):
        assert isinstance(session, DoNotUse)
        assert cluster_name == self.name
        
        # TODO
        return None, self.cluster_status_response
    
    def create_nodes(self, session, cluster_name, request):
        assert isinstance(session, DoNotUse)
        assert cluster_name == self.name
        
        assert self.expected_create_nodes_request["sets"] == request.to_dict()["sets"], "\n%s\n%s" % (self.expected_create_nodes_request["sets"], request.to_dict()["sets"])
        resp = NodeCreationResult()
        resp.sets = []
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
            cluster_status = ClusterStatus()
#             mock_subprocess.expect(["scontrol", "show", "hostlist", "ondemand-pg0-1"], "ondemand-pg0-1")
            mock_cluster.cluster_status_response = cluster_status
#             mock_cluster._started_nodes.append({"Template": "ondemand", "Name": "ondemand-pg0-1"})
            
            cluster_status.nodes = []
            nodearray_status = ClusterNodearrayStatus()
            nodearray_status.name = "ondemand"
            cluster_status.nodearrays = [nodearray_status]
            
            bucket = NodearrayBucketStatus()
            nodearray_status.buckets = [bucket]
            
            bucket.max_count = 2
            
            bucket.definition = NodearrayBucketStatusDefinition()
            bucket.definition.machine_type = "Standard_D2_v2"
            
            nodearray_status.nodearray = {"MachineType": bucket.definition.machine_type,
                                          "Configuration": {"slurm": {"autoscale": True}}}
            
            vm = NodearrayBucketStatusVirtualMachine()
            vm.memory = 4
            vm.vcpu_count = 2
            bucket.virtual_machine = vm
            
            # 
            cluster_wrapper = clusterwrapper.ClusterWrapper(mock_cluster.name, DoNotUse(), DoNotUse(), mock_cluster)
            partitions = cyclecloud_slurm.fetch_partitions(cluster_wrapper, mock_subprocess)
            self.assertEquals(1, len(partitions))
            partition = partitions["ondemand"]
            self.assertEquals("ondemand", partition.name)
            self.assertEquals("ondemand", partition.nodearray)
            self.assertEquals(None, partition.node_list)
            self.assertTrue(partition.is_default)
            self.assertEquals(bucket.definition.machine_type, partition.machine_type)
            self.assertEquals(40, partition.max_scaleset_size)
            self.assertEquals(2, partition.max_vm_count)
            self.assertEquals(4, partition.memory)
            self.assertEquals(2, partition.vcpu_count)
            del partition
            
            cluster_status.nodes = [{"Name": "ondemand-100", "Template": "ondemand"},
                                    {"Name": "ondemand-101", "Template": "ondemand"},
                                    {"Name": "ondemand-102", "Template": "ondemand"}]
            
            # now there are pre-existing nodes, so just use those to determine the node_list
            mock_subprocess.expect("scontrol show hostlist ondemand-100,ondemand-101,ondemand-102", "ondemand-10[0-2]")
            partitions = cyclecloud_slurm.fetch_partitions(cluster_wrapper, mock_subprocess)
            self.assertEquals("ondemand-10[0-2]", partitions["ondemand"].node_list)
            
            # change max scale set size
            mock_subprocess.expect("scontrol show hostlist ondemand-100,ondemand-101,ondemand-102", "ondemand-10[0-2]")
            nodearray_status.nodearray["Azure"] = {"MaxScalesetSize": 2}
            partitions = cyclecloud_slurm.fetch_partitions(cluster_wrapper, mock_subprocess)
            self.assertEquals("ondemand-10[0-2]", partitions["ondemand"].node_list)
            self.assertEquals(2, partitions["ondemand"].max_scaleset_size)
            
            # ensure we can disable autoscale
            nodearray_status.nodearray["Configuration"]["slurm"]["autoscale"] = False
            partitions = cyclecloud_slurm.fetch_partitions(cluster_wrapper, mock_subprocess)
            self.assertEquals(0, len(partitions))
            
            # default for autoscale is false
            nodearray_status.nodearray["Configuration"]["slurm"].pop("autoscale")
            partitions = cyclecloud_slurm.fetch_partitions(cluster_wrapper, mock_subprocess)
            self.assertEquals(0, len(partitions))
            
    def test_create_nodes(self):
        partitions = {}
        partitions["ondemand"] = Partition("ondemand", "ondemand", "Standard_D2_v2", is_default=True, max_scaleset_size=3, vcpu_count=2, memory=4, max_vm_count=8)
#         partitions["lowprio"] = Partition("lowprio", "lowprio", "Standard_D2_v2", is_default=False, max_scaleset_size=100, vcpu_count=2, memory=4, max_vm_count=8)
        
        mock_cluster = MockClusterModule()
        cluster_wrapper = clusterwrapper.ClusterWrapper(mock_cluster.name, DoNotUse(), DoNotUse(), mock_cluster)
        # create 3 placement groups for ondemand with sizes 3,3,2 (3 + 3 + 2 = 8, which is the max_vm_count_
        # al
        expected_request = {'sets': [
#             {'count': 8,
#              'definition': {'machineType': 'Standard_D2_v2'},
#              'nodeAttributes': {'StartAutomatically': False,
#                                 'State': 'Off',
#                                 'TargetState': 'Terminated'},
#              'nodearray': 'lowprio',
#              'placementGroupId': 'lowprio-Standard_D2_v2-pg0'},
            {'count': 3,
             'nameFormat': 'ondemand-pg0-%d',
             'nameOffset': 1,
             'definition': {'machineType': 'Standard_D2_v2'},
             'nodeAttributes': {'StartAutomatically': False,
                                'Fixed': True},
             'nodearray': 'ondemand',
             'placementGroupId': 'ondemand-Standard_D2_v2-pg0'},
            {'count': 3,
             'nameFormat': 'ondemand-pg1-%d',
             'nameOffset': 1,
             'definition': {'machineType': 'Standard_D2_v2'},
             'nodeAttributes': {'StartAutomatically': False,
                                'Fixed': True},
             'nodearray': 'ondemand',
             'placementGroupId': 'ondemand-Standard_D2_v2-pg1'},
            {'count': 2,
             'nameFormat': 'ondemand-pg2-%d',
             'nameOffset': 1,
             'definition': {'machineType': 'Standard_D2_v2'},
             'nodeAttributes': {'StartAutomatically': False,
                                'Fixed': True},
             'nodearray': 'ondemand',
             'placementGroupId': 'ondemand-Standard_D2_v2-pg2'}]}
        mock_cluster.expected_create_nodes_request = expected_request
        cyclecloud_slurm._create_nodes(partitions, cluster_wrapper)
        
        partitions["ondemand"].max_vm_count *= 2
        
        self.assertRaises(CyclecloudSlurmError, lambda: cyclecloud_slurm._create_nodes(partitions, cluster_wrapper, existing_policy=ExistingNodePolicy.Error))
        cyclecloud_slurm._create_nodes(partitions, cluster_wrapper, existing_policy=ExistingNodePolicy.AllowExisting)
        
    def test_generate_slurm_conf(self):
        writer = cStringIO.StringIO()
        partitions = OrderedDict()
        partitions["ondemand"] = Partition("custom_partition_name", "ondemand", "Standard_D2_v2", is_default=True, max_scaleset_size=3, vcpu_count=2, memory=4, max_vm_count=8)
        partitions["lowprio"] = Partition("lowprio", "lowprio", "Standard_D2_v3", is_default=False, max_scaleset_size=100, vcpu_count=2, memory=3.5, max_vm_count=8)

        partitions["ondemand"].node_list = "ondemand-10[1-8]"
        partitions["lowprio"].node_list = "lowprio-[1-8]"
        with MockSubprocessModule() as mock_subprocess:
            cyclecloud_slurm._generate_slurm_conf(partitions, writer, mock_subprocess)
        result = writer.getvalue().strip()
        expected = '''
PartitionName=custom_partition_name Nodes=ondemand-10[1-8] Default=YES MaxTime=INFINITE State=UP
Nodename=ondemand-[1-3] Feature=cloud STATE=CLOUD CPUs=2 RealMemory=4096
Nodename=ondemand-[4-6] Feature=cloud STATE=CLOUD CPUs=2 RealMemory=4096
Nodename=ondemand-[7-8] Feature=cloud STATE=CLOUD CPUs=2 RealMemory=4096
PartitionName=lowprio Nodes=lowprio-[1-8] Default=NO MaxTime=INFINITE State=UP
Nodename=lowprio-[1-8] Feature=cloud STATE=CLOUD CPUs=2 RealMemory=3584'''.strip()
        for e, a in zip(result.splitlines(), expected.splitlines()):
            assert e == a, "\n%s\n%s" % (e, a)
        
    def test_generate_topology(self):
        writer = cStringIO.StringIO()
        partitions = OrderedDict()
        partitions["ondemand"] = Partition("custom_partition_name", "ondemand", "Standard_D2_v2", is_default=True, max_scaleset_size=3, vcpu_count=2, memory=4, max_vm_count=8)
        partitions["lowprio"] = Partition("lowprio", "lowprio", "Standard_D2_v3", is_default=False, max_scaleset_size=100, vcpu_count=2, memory=3.5, max_vm_count=8)
        partitions["ondemand"].node_list = "ondemand-10[1-8]"
        partitions["lowprio"].node_list = "lowprio-[1-8]"
        
        cyclecloud_slurm._generate_topology(partitions, writer)
        result = writer.getvalue().strip()
        expected = '''
SwitchName=custom_partition_name-ondemand Switches=custom_partition_name-ondemand-Standard_D2_v2-pg[0-2]
SwitchName=custom_partition_name-ondemand-Standard_D2_v2-pg0 Nodes=ondemand-[1-3]
SwitchName=custom_partition_name-ondemand-Standard_D2_v2-pg1 Nodes=ondemand-[4-6]
SwitchName=custom_partition_name-ondemand-Standard_D2_v2-pg2 Nodes=ondemand-[7-8]
SwitchName=lowprio-lowprio Switches=lowprio-lowprio-Standard_D2_v3-pg[0-0]
SwitchName=lowprio-lowprio-Standard_D2_v3-pg0 Nodes=lowprio-[1-8]'''.strip()
        for e, a in zip(result.splitlines(), expected.splitlines()):
            assert e == a, "\n%s\n%s" % (e, a)        
    def test_resume(self):
        mock_cluster = MockClusterModule()
        cluster_wrapper = clusterwrapper.ClusterWrapper(mock_cluster.name, DoNotUse(), DoNotUse(), mock_cluster)
        
        with MockSubprocessModule() as subprocess_module:
            
            subprocess_module.expect("scontrol update NodeName=ondemand-1 NodeAddr=10.1.0.0 NodeHostname=10.1.0.0".split())
            mock_cluster.expected_start_nodes_request = {'names': ['ondemand-1']}
            cyclecloud_slurm._resume(["ondemand-1"], cluster_wrapper, subprocess_module)
            
            subprocess_module.expect("scontrol update NodeName=ondemand-1 NodeAddr=10.1.0.0 NodeHostname=10.1.0.0".split())
            subprocess_module.expect("scontrol update NodeName=ondemand-44 NodeAddr=10.1.0.1 NodeHostname=10.1.0.1".split())
            mock_cluster.expected_start_nodes_request = {'names': ['ondemand-1', 'ondemand-44']}
            cyclecloud_slurm._resume(["ondemand-1", "ondemand-44"], cluster_wrapper, subprocess_module)
