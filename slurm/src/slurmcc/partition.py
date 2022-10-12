# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#

import logging
import re
from collections import OrderedDict
from typing import Dict, List

from hpc.autoscale.node.bucket import NodeBucket
from hpc.autoscale.node.limits import BucketLimits
from hpc.autoscale.node.nodemanager import NodeManager
from hpc.autoscale.hpctypes import PlacementGroup

from hpc.autoscale import util as hpcutil

from . import util as slutil


class Partition:
    def __init__(
        self,
        name: str,
        nodearray: str,
        nodename_prefix: str,
        machine_type: str,
        is_default: bool,
        is_hpc: bool,
        max_scaleset_size: int,
        buckets: List[NodeBucket],
        max_vm_count: int,
        use_pcpu: bool = False,
    ) -> None:
        self.name = name
        self.nodearray = nodearray
        self.nodename_prefix = nodename_prefix
        self.machine_type = machine_type
        self.is_default = is_default
        self.is_hpc = is_hpc
        if not is_hpc:
            assert len(buckets) == 1
        assert len(buckets) > 0
        self.max_scaleset_size = max_scaleset_size
        self.vcpu_count = buckets[0].vcpu_count
        slurm_memory = buckets[0].resources.get("slurm_memory")
        if slurm_memory:
            self.memory = int(slurm_memory.convert_to("m").value)
        else:
            self.memory = int(buckets[0].memory.convert_to("m").value)

        self.max_vm_count = sum([b.max_count for b in buckets])
        self.buckets = buckets
        self.use_pcpu = use_pcpu
        self.node_list_by_pg: Dict[PlacementGroup, List[str]] = _construct_node_list(
            self
        )

    def bucket_for_node(self, node_name: str) -> NodeBucket:
        for pg, node_list in self.node_list_by_pg.items():
            if node_name in node_list:
                for bucket in self.buckets:
                    if bucket.placement_group == pg:
                        return bucket
        raise RuntimeError()

    @property
    def node_list(self) -> str:
        return slutil.to_hostlist(self.all_nodes())
    
    def all_nodes(self) -> List[str]:
        ret = []
        for bucket in self.buckets:
            ret.extend(self.node_list_by_pg[bucket.placement_group])
        ret = sorted(ret, key=slutil.get_sort_key_func(self.is_hpc))
        return ret

    @property
    def pcpu_count(self) -> int:
        return self.buckets[0].pcpu_count

    @property
    def gpu_count(self) -> int:
        return self.buckets[0].gpu_count


def _construct_node_list(partition: Partition) -> Dict[PlacementGroup, List[str]]:
    name_format = partition.nodename_prefix + "{}-%d"

    valid_node_names = {}

    vm_count = 0
    for bucket in partition.buckets:
        valid_node_names[bucket.placement_group] = list()
        while (
            vm_count < partition.max_vm_count
        ):
            name_index = vm_count + 1
            node_name = name_format.format(
                partition.nodearray
            ) % (name_index)
            # print(f"RDH node_name={node_name}")
            valid_node_names[bucket.placement_group].append(node_name)
            vm_count += 1
    return valid_node_names


def fetch_partitions(node_mgr: NodeManager) -> Dict[str, Partition]:
    """
    Construct a mapping of SLURM partition name -> relevant nodearray information.
    There must be a one-to-one mapping of partition name to nodearray. If not, first one wins.
    """

    partitions = OrderedDict()

    split_buckets = hpcutil.partition(
        node_mgr.get_buckets(), lambda b: (b.nodearray, b.vm_size)
    )
    for buckets in split_buckets.values():
        nodearray_name = buckets[0].nodearray
        slurm_config = buckets[0].software_configuration.get("slurm", {})
        is_hpc = False #str(slurm_config.get("hpc", True)).lower() == "true"
        is_autoscale = slurm_config.get("autoscale", True)  # TODO
        if is_autoscale is None:
            logging.warning(
                "Nodearray %s does not define slurm.autoscale, skipping.",
                nodearray_name,
            )
            continue

        if is_autoscale is False:
            logging.debug(
                "Nodearray %s explicitly defined slurm.autoscale=false, skipping.",
                nodearray_name,
            )
            continue

        if is_hpc:
            buckets = [b for b in buckets if b.placement_group]
        else:
            buckets = [b for b in buckets if not b.placement_group]
            assert len(buckets) == 1
        
        if not buckets:
            continue

        if not nodearray_name:
            logging.error("Name is not defined for nodearray. Skipping")
            continue

        partition_name = slurm_config.get("partition", nodearray_name)
        unescaped_nodename_prefix = slurm_config.get("node_prefix") or ""

        nodename_prefix = re.sub("[^a-zA-Z0-9-]", "-", unescaped_nodename_prefix)

        if unescaped_nodename_prefix != nodename_prefix:
            logging.warning(
                "slurm.node_prefix for partition %s was converted from '%s' to '%s' due to invalid hostname characters.",
                nodearray_name,
                unescaped_nodename_prefix,
                nodename_prefix,
            )

        machine_type = buckets[0].vm_size
        if not machine_type:
            logging.warning(
                "MachineType not defined for nodearray %s. Skipping", nodearray_name
            )
            continue

        if partition_name in partitions:
            logging.warning(
                "Same partition defined for two different nodearrays. Ignoring nodearray %s",
                nodearray_name,
            )
            continue

        limits: BucketLimits = buckets[0].limits

        if limits.max_count <= 0:
            logging.info(
                "Bucket has a max_count <= 0, defined for machinetype=='%s'. Skipping",
                machine_type,
            )
            continue

        max_scaleset_size = buckets[0].max_placement_group_size

        # dampen_memory = float(slurm_config.get("dampen_memory") or 5) / 100

        if not is_hpc:
            max_scaleset_size = 2 ** 31

        use_pcpu = str(slurm_config.get("use_pcpu", True)).lower() == "true"

        partitions[partition_name] = Partition(
            partition_name,
            nodearray_name,
            nodename_prefix,
            machine_type,
            slurm_config.get("default_partition", False),
            is_hpc,
            max_scaleset_size,
            buckets,
            limits.max_count,
            use_pcpu=use_pcpu,
        )

        # if node_bucket.nodes:
        #     sorted_nodes = sorted(
        #         node_bucket.nodes,
        #         key=slutil.get_sort_key_func(partitions[partition_name].is_hpc),
        #     )
        #     partitions[partition_name].node_list = slutil.to_hostlist(
        #         ",".join(sorted_nodes)  # type: ignore
        #     )

    partitions_list = list(partitions.values())
    default_partitions = [p for p in partitions_list if p.is_default]

    if len(default_partitions) == 0:
        logging.warning("slurm.default_partition was not set on any nodearray.")

        # one nodearray, just assume it is the default
        if len(partitions_list) == 1:
            logging.info("Only one nodearray was defined, setting as default.")
            partitions_list[0].is_default = True

    elif len(default_partitions) > 1:
        # no partition is default
        logging.warning("slurm.default_partition was set on more than one nodearray!")

    return partitions
