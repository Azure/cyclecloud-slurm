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
        self.node_list_by_pg: Dict[
            Optional[PlacementGroup], List[str]
        ] = _construct_node_list(self)
        self.dynamic_config = dynamic_config
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

    def add_dynamic_node(
        self, node_name: str, placement_group: Optional[PlacementGroup] = None
    ) -> None:
        assert self.dynamic_config, "Cannot add dynamic node to non-dynamic partition"
        if placement_group not in self.node_list_by_pg:
            self.node_list_by_pg[placement_group] = []

        node_list = self.node_list_by_pg[placement_group]
        if node_name not in node_list:
            node_list.append(node_name)

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


def _construct_node_list(
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
            # print(f"RDH node_name={node_name}")
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

        nodename_prefix = nodename_prefix.lower()

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

            # dampen_memory = float(slurm_config.get("dampen_memory") or 5) / 100

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
