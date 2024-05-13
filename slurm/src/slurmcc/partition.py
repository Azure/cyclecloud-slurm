# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#

import re
from typing import Dict, List, Optional

from hpc.autoscale import hpclogging as logging
from hpc.autoscale import util as hpcutil
from hpc.autoscale.hpctypes import PlacementGroup
from hpc.autoscale.node.bucket import NodeBucket
from hpc.autoscale.node.limits import BucketLimits
from hpc.autoscale.node.nodemanager import NodeManager

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
        dynamic_config: Optional[str] = None,
        over_allocation_thresholds: Dict = {},
        nodearray_machine_types: Optional[List[str]] = None,
        dampen_memory: Optional[float] = None,
    ) -> None:
        self.name = name
        self.nodearray = nodearray
        self.nodename_prefix = nodename_prefix
        self.machine_type = machine_type
        nodearray_machine_types = nodearray_machine_types or [self.machine_type]
        self.nodearray_machine_types = [x.lower() for x in nodearray_machine_types]
        self.is_default = is_default
        self.is_hpc = is_hpc
        if not is_hpc:
            assert len(buckets) == 1
        assert len(buckets) > 0
        self.max_scaleset_size = max_scaleset_size
        self.vcpu_count = buckets[0].vcpu_count
        memory_mb = buckets[0].memory.convert_to("m").value 
        if dampen_memory is not None:
            if buckets[0].resources.get("slurm_memory"):
                logging.warning("Because slurm.dampen_memory is defined, slurm_memory as defined in the autoscale.json will be ignored.")
            to_decrement = max(1024, memory_mb * dampen_memory)
            self.memory = int(memory_mb - to_decrement)
        else:
            slurm_memory = buckets[0].resources.get("slurm_memory")
            if slurm_memory:
                self.memory = int(slurm_memory.convert_to("m").value)
            else:
                to_decrement = max(1024, memory_mb * 0.05)
                self.memory = int(memory_mb - to_decrement)

        self.max_vm_count = sum([b.max_count for b in buckets])
        self.buckets = buckets
        self.use_pcpu = use_pcpu
        self.dynamic_config = dynamic_config
        # cache node_list property for dynamic partitions
        self.__dynamic_node_list_cache = None
        self.node_list_by_pg: Dict[
            Optional[PlacementGroup], List[str]
        ] = _construct_node_list(self)
        
        self.over_allocation_thresholds = over_allocation_thresholds

        self.features = []
        if self.dynamic_config:
            toks = self.dynamic_config.replace('"', "").replace("'", "").split()

            for tok in toks:
                if "=" in tok:
                    key, value = tok.split("=", 1)
                    if key.lower() == "feature":
                        self.features = value.strip().split(",")

        
    def bucket_for_node(self, node_name: str) -> NodeBucket:
        for pg, node_list in self.node_list_by_pg.items():
            if node_name in node_list:
                for bucket in self.buckets:
                    if bucket.placement_group == pg:
                        return bucket
        raise RuntimeError()
    
    _SLURM_NODES_CACHE = None

    @classmethod
    def _slurm_nodes(cls) -> List[Dict[str, str]]:
        if not cls._SLURM_NODES_CACHE:
            cls._SLURM_NODES_CACHE = slutil.show_nodes()
        return cls._SLURM_NODES_CACHE

    @property
    def node_list(self) -> str:
        if not self.dynamic_config:
            return slutil.to_hostlist(self._static_all_nodes())
        # with dynamic nodes, we only look at those defined in the partition
        if not self.__dynamic_node_list_cache:
            if not slutil.is_slurmctld_up():
                logging.warning("While slurmctld is down, dynamic nodes can not be queried at this time.")
                return ""
            ret: List[str] = []
            all_slurm_nodes = Partition._slurm_nodes()
            for node in all_slurm_nodes:
                partitions = node["Partitions"].split(",")
                if self.name in partitions:
                    # only include nodes that have the same vm_size declared as a feature
                    features = (node.get("AvailableFeatures") or "").lower().split(",")
                    if self.machine_type.lower() in features:
                        ret.append(node["NodeName"])
                    else:
                        matches_another_vm_size = set(self.nodearray_machine_types).intersection(set(features))
                        if matches_another_vm_size:
                            # this node has a declared vm_size, but it's not the one we're looking for.
                            continue

                        # we only use the highest priority vm_size as the default - let that 
                        # partition object handle this.
                        if self.machine_type.lower() != self.nodearray_machine_types[0]:
                            continue

                        # anything that starts with standard_ "looks" like a vm_size, at least for logging purposes
                        possible_vm_sizes = [f for f in features if f.startswith("standard_")]
                        if possible_vm_sizes:
                            # we do allow users to use features that start with standard_, but we 
                            # want to warn them at least. For example, someone puts standard_f2_2v instead of _v2
                            # or say someone unchecks the relevant vm_size from the CycleCloud cluster.
                            logging.warning("Found potential vm_size %s - however none match approved vm sizes %s. Is this a typo?",
                                             ",".join(possible_vm_sizes),
                                             ",".join(self.nodearray_machine_types))

                        # if we get here, we will just use our  machine type as the vm_size.
                        # HOWEVER we bump the logging up to warning if there are multiple vm_sizes defined
                        # for this nodearray, as users _should_ be specific about which vm size they want when
                        # allowing more than one per nodearray.
                        log_level = logging.DEBUG if len(self.nodearray_machine_types) > 1 else logging.WARNING
                        logging.log(log_level,
                                    "No vm_size feature for node %s is defined, assuming vm_size %s",
                                    node["NodeName"],
                                    self.machine_type)
                        ret.append(node["NodeName"])
                        
            self.__dynamic_node_list_cache = slutil.to_hostlist(ret) if ret else ""
            
        return self.__dynamic_node_list_cache
    
    def _static_all_nodes(self) -> List[str]:
        ret = []
        for bucket in self.buckets:
            ret.extend(self.node_list_by_pg[bucket.placement_group])
        ret = sorted(ret, key=slutil.get_sort_key_func(self.is_hpc))
        return ret
    
    def all_nodes(self) -> List[str]:
        if not self.dynamic_config:
            return self._static_all_nodes()        
        return slutil.from_hostlist(self.node_list)

    @property
    def pcpu_count(self) -> int:
        return self.buckets[0].pcpu_count

    @property
    def gpu_count(self) -> int:
        if "slurm_gpus" in self.buckets[0].resources:
            return self.buckets[0].resources["slurm_gpus"]
        return self.buckets[0].gpu_count


def _construct_node_list(
    partition: Partition,
) -> Dict[Optional[PlacementGroup], List[str]]:
    if partition.dynamic_config:
        return _construct_dynamic_node_list(partition)
    else:
        return _construct_static_node_list(partition)


def _construct_dynamic_node_list(
    partition: Partition,
) -> Dict[Optional[PlacementGroup], List[str]]:
    part_node_names = slutil.from_hostlist(partition.node_list)
    return {None: part_node_names}


def _construct_static_node_list(
    partition: Partition,
) -> Dict[Optional[PlacementGroup], List[str]]:
    name_format = partition.nodename_prefix + "{}-%d"

    valid_node_names = {}

    vm_count = 0
    for bucket in partition.buckets:
        valid_node_names[bucket.placement_group] = list()
        while vm_count < partition.max_vm_count:
            name_index = vm_count + 1
            node_name = name_format.format(partition.nodearray) % (name_index)
            valid_node_names[bucket.placement_group].append(node_name)
            vm_count += 1
    return valid_node_names


def _parse_default_overallocations(
    partition_name: str, overallocation_expr: List
) -> Dict:
    working_overalloc_thresholds = {}

    if len(overallocation_expr) == 0 or len(overallocation_expr) % 2 == 1:
        logging.error(f"Invalid slurm.overallocation expression for {partition_name}.")
        logging.error("Must have an even number of elements, larger than 0. Ignoring")
        return {}
    else:
        for i in range(0, len(overallocation_expr), 2):
            threshold = overallocation_expr[i]
            percentage = overallocation_expr[i + 1]
            try:
                threshold = int(threshold)
            except:
                logging.error(
                    f"Invalid threshold at index {i} for partition {partition_name} - {threshold}, expected an integer.",
                    threshold,
                )
                logging.error("You will have to edit autoscale.json manually instead.")
                return {}

            try:
                percentage = float(percentage)
                if percentage < 0 or percentage > 1:
                    logging.error(
                        f"Invalid percentage at index {i} for {partition_name} - {percentage}. It must be a number between [0, 1]"
                    )
                    logging.error(
                        "You will have to edit autoscale.json manually instead."
                    )
                    return {}
            except:
                logging.error(
                    f"Invalid threshold at index {i} for partition {partition_name} - {threshold}, expected an integer.",
                    threshold,
                )
                logging.error("You will have to edit autoscale.json manually instead.")
                return {}

            working_overalloc_thresholds[str(threshold)] = percentage
        return working_overalloc_thresholds


def fetch_partitions(
    node_mgr: NodeManager, include_dynamic: bool = False
) -> List[Partition]:
    """
    Construct a mapping of SLURM partition name -> relevant nodearray information.
    There must be a one-to-one mapping of partition name to nodearray. If not, first one wins.
    """

    all_partitions: List[Partition] = []

    split_buckets = hpcutil.partition(
        node_mgr.get_buckets(), lambda b: (b.nodearray, b.vm_size)
    )

    # dict[nodearray, List[vm_size]]
    nodearray_vm_size: Dict[str, List[str]] = {}
    for nodearray, vm_size in split_buckets.keys():
        if nodearray not in nodearray_vm_size:
            nodearray_vm_size[nodearray] = []
        nodearray_vm_size[nodearray].append(vm_size)

    for buckets in split_buckets.values():
        nodearray_name = buckets[0].nodearray
        slurm_config = buckets[0].software_configuration.get("slurm", {})
        dynamic_config = slurm_config.get("dynamic_config")
        is_hpc = str(slurm_config.get("hpc", True)).lower() == "true"
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
        all_buckets = buckets
        if is_hpc:
            # TODO RDH there should only be one long term.
            # we need to allow the user to pick a new placement group
            # maybe...
            buckets = [b for b in buckets if b.placement_group]
        else:
            buckets = [b for b in buckets if not b.placement_group]

        assert (
            len(buckets) == 1
        ), f"{[(b.nodearray, b.placement_group, is_hpc) for b in all_buckets]}"

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

        if len(buckets) > 1 and not dynamic_config:
            logging.warning(
                "Multiple buckets defined for nodearray %s, but no dynamic_config. Using first bucket (vm_size or placement group) only.",
                nodearray_name,
            )
            buckets = [buckets[0]]

        for bucket in buckets:
            machine_type = bucket.vm_size
            if not machine_type:
                logging.warning(
                    "MachineType not defined for nodearray %s. Skipping", nodearray_name
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

            dampen_memory = None
            dampen_memory_str = slurm_config.get("dampen_memory")
            if dampen_memory_str:
                dampen_memory = int(dampen_memory_str) / 100.0


            if not is_hpc:
                max_scaleset_size = 2 ** 31

            use_pcpu = str(slurm_config.get("use_pcpu", True)).lower() == "true"

            overallocation_expr = slurm_config.get("overallocation") or []
            over_allocation_thresholds = {}
            if overallocation_expr:
                over_allocation_thresholds = _parse_default_overallocations(
                    partition_name, overallocation_expr
                )

            all_partitions.append(
                Partition(
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
                    dynamic_config=dynamic_config,
                    over_allocation_thresholds=over_allocation_thresholds,
                    nodearray_machine_types=nodearray_vm_size.get(nodearray_name),
                    dampen_memory=dampen_memory,
                )
            )

    filtered_partitions = []
    by_name = hpcutil.partition(all_partitions, lambda p: p.name)
    for pname, parts in by_name.items():
        all_dyn = set([bool(p.dynamic_config) for p in parts])

        if len(all_dyn) > 1:
            logging.error(
                "Found two partitions with the same name, but only one is dynamic."
            )
            disabled_parts_message = ["/".join([p.name, p.nodearray]) for p in parts]
            logging.error(f"Disabling {disabled_parts_message}")
        else:
            if len(parts) > 1 and False in all_dyn:
                logging.error(
                    "Only partitions with slurm.dynamic_config may point to more than one nodearray."
                )
                disabled_parts_message = [
                    "/".join([p.name, p.nodearray]) for p in parts
                ]
                logging.error(f"Disabling {disabled_parts_message}")
            else:
                filtered_partitions.extend(parts)

    default_partitions = [p for p in filtered_partitions if p.is_default]

    if len(default_partitions) == 0:
        logging.warning("slurm.default_partition was not set on any nodearray.")

        # one nodearray, just assume it is the default
        if len(filtered_partitions) == 1:
            logging.info("Only one nodearray was defined, setting as default.")
            filtered_partitions[0].is_default = True

    elif len(default_partitions) > 1:
        # no partition is default
        logging.warning("slurm.default_partition was set on more than one nodearray!")

    return filtered_partitions
