from slurmcc import allocation, cli, util
import abc
import os
import time
from hpc.autoscale.node.node import Node
from hpc.autoscale.util import load_config
from hpc.autoscale import hpclogging as logging


class NodeSource(abc.ABC):
    @abc.abstractmethod
    def get_nodes(self) -> list[Node]: ...


class NodeManagerSource(NodeSource):
    def get_nodes(self) -> list[Node]:
        node_mgr = cli.new_node_manager()
        return node_mgr.get_nodes()


class AzslurmDaemon:

    def __init__(self, node_source: NodeSource, keep_alive_conf: str = os.path.realpath("/etc/slurm/keep_alive.conf")) -> None:
        self.node_source = node_source
        self.sync_nodes = allocation.SyncNodes()
        self.slurm_nodes = allocation.SlurmNodes(allocation.SuspendExcNodesSerializer(keep_alive_conf))

    def run_once(self) -> None:
        start = time.time()
        logging.debug("begin azslurmd")
        self.slurm_nodes.refresh()
        self.converge_nodes()
        end = time.time()
        duration = end - start
        logging.info("Completed azslurmd in %.1fs" % duration)
    
    def converge_nodes(self) -> None:
        cc_nodes = self.node_source.get_nodes()
        # follow the symlink
        self.sync_nodes.sync_nodes(self.slurm_nodes, cc_nodes)


@cli.init_power_saving_log
def azslurmd(sleep_time: int = 15) -> None:
    """Run the main loop of the azslurm daemon. Writes log to azslurmd.log under /opt/azurehpc/slurm/logs"""
    logging.info("azslurmd is running with PID=%s", os.getpid())
    azslurm_daemon = AzslurmDaemon(NodeManagerSource())
    while True:
        try:
            azslurm_daemon.run_once()
            time.sleep(sleep_time)
        except InterruptedError:
            logging.warning("azslurmd recieved sigkill")
            return
        except Exception:
            logging.exception("azslurmd hit an exception - sleeping")
            time.sleep(sleep_time)


def run(config_path: str) -> None:
    config = load_config(config_path)
    logging.set_context(f"[azslurmd]")
    logging.initialize_logging(config)
    sleep_time = (config.get("azslurmd") or {}).get("sleep_time") or 15
    azslurmd(max(1, sleep_time))
