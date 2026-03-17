import asyncio
import argparse
import logging
import logging.config
import signal
import sys
import time
import os
from importlib import resources
from prometheus_client import CollectorRegistry, Metric, Counter, Gauge, Summary
from abc import ABC, abstractmethod
from functools import partial
from collections import namedtuple
from aiohttp import web
from prometheus_client.aiohttp import make_aiohttp_handler
from typing import Iterator, List, Union

log = logging.getLogger("root")
CommandResult = namedtuple("CommandResult", ["returncode", "stdout", "stderr"])

class NoCollectorsFoundException(Exception):
    pass

class HTTPServerFailedException(Exception):
    pass

class CommandFailedException(Exception):
    """Raised when a subprocess exits with a non-zero return code."""
    def __init__(self, cmd: str, returncode: int, stderr: str):
        self.cmd = cmd
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(f"Command '{cmd}' failed with exit code {returncode}: {stderr}")

class CommandTimedOutException(Exception):
    """Raised when a subprocess exceeds its timeout."""
    def __init__(self, cmd: str, timeout: int):
        self.cmd = cmd
        self.timeout = timeout
        super().__init__(f"Command '{cmd}' timed out after {timeout}s and was killed")
class BaseCollector(ABC):
    """
    Abstract base class for collecting metrics from SLURM.
    This class provides the foundational structure for implementing metric collectors
    that periodically gather data from SLURM systems, format them as Prometheus metrics,
    and expose them for scraping. It handles asynchronous command execution and periodic
    task scheduling to decouple individual collector cycles from Prometheus scrape intervals.
    """
    @abstractmethod
    def initialize(self) -> None:
        """
        Validate that all dependencies required for this collector are available.
        """
    ...

    @abstractmethod
    def start(self) -> None:
        """
        Start the periodic metrics collection loop for the collector to query data,
        parse the output to create Prometheus formatted metrics, and cache the results at each interval. Decouples
        each collector's collection cycle and the prometheus scrape
        """
        ...

    @abstractmethod
    def export_metrics(self) -> List[Union[Gauge,Counter,Summary]]:
        """
        Return the current set of collected metrics from each collector's cache
        for Prometheus to scrape.
        Note: No locking required for cached metrics because of
        GIL and asynchronous functions running in one thread. This may change with future
        Python versions.
        """
        ...

    async def run_command(self, *args, timeout=120,) -> CommandResult:
        """
        Executes any command needed for metric collection asynchronously
        """
        start = time.monotonic()
        cmd_str = " ".join(str(a) for a in args)
        proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            async with asyncio.timeout(timeout):
                stdout, stderr = await proc.communicate()
        #TODO: Explore what metrics to export when commands error/time out, right now we export stale metrics
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise CommandTimedOutException(cmd_str, timeout)
        elapsed = time.monotonic() - start
        log.debug("Command: %s, Exit code: %d, Time Elapsed: %f", cmd_str, proc.returncode, elapsed)
        if proc.returncode != 0:
            raise CommandFailedException(cmd_str, proc.returncode, stderr.decode())
        return CommandResult(returncode=proc.returncode, stdout=stdout, stderr=stderr)

    def launch_task(self, func, interval) -> None:
        """
        Launch an asynchronous task that schedules a callable function
        ie, the full collection cycle of querying, parsing and caching metrics,
        to be run at regular intervals.
        """

        asyncio.create_task(self.__schedule(func, interval))

    async def __schedule(self, func, interval: int) -> None:
        """
        Schedule a callable function to periodically run at each interval
        """
        if callable(func):
            await func()
            loop = asyncio.get_running_loop()
            loop.call_later(interval, partial(self.launch_task, func, interval))
        else:
            log.error(f"func {repr(func)} is not callable")

class CompositeCollector:
    """
    A composite collector that aggregates metrics from multiple SLURM and Azure-specific data sources.
    This class manages the initialization and coordination of multiple specialized collectors
    (Squeue, Sacct, Sinfo, Azslurm, and Jetpack) that gather different types of metrics from
    a SLURM cluster and Azure environment. It provides a unified interface for exporting
    collected metrics to Prometheus.
    """
    def __init__(self):
        self.collectors = []

    def initialize_collectors(self) -> None:
        """
        Initialize and start all collectors concurrently to begin metric collection cycle
        at each downstream interval.
        - Squeue: Collects job queue information
        - Sacct: Collects job accounting data
        - Sinfo: Collects node/partition
        - Azslurm: Collects partition specs
        - Jetpack: Collects cluster specs
        """
        try:
            from exporter.squeue import Squeue, SqueueNotAvailException
            squeue = Squeue()
            squeue.initialize()
        except SqueueNotAvailException:
            log.warning("squeue is not available, disabling squeue metrics")
        else:
            self.collectors.append(squeue)

        try:
            from exporter.sacct import Sacct, SacctNotAvailException
            sacct = Sacct()
            sacct.initialize()
        except SacctNotAvailException:
            log.warning("Accounting is disabled, disabling sacct metrics")
        else:
            self.collectors.append(sacct)

        try:
            from exporter.sinfo import Sinfo, SinfoNotAvailException
            sinfo = Sinfo()
            sinfo.initialize()
        except SinfoNotAvailException:
            log.warning("sinfo is not available, disabling sinfo metrics")
        else:
            self.collectors.append(sinfo)

        try:
            from exporter.azslurm import Azslurm, AzslurmNotAvailException
            azslurm = Azslurm()
            azslurm.initialize()
        except AzslurmNotAvailException:
            log.warning("azslurm is not available, disabling azslurm metrics")
        else:
            self.collectors.append(azslurm)

        try:
            from exporter.jetpack import Jetpack, JetpackNotAvailException
            jetpack = Jetpack()
            jetpack.initialize()
        except JetpackNotAvailException:
            log.warning("jetpack is not available, disabling jetpack metrics")
        else:
            self.collectors.append(jetpack)

        if not self.collectors:
            log.error("No collectors initialized")
            raise NoCollectorsFoundException
        for collector in self.collectors:
            collector.start()

    def export_metrics(self) -> Iterator[Union[Gauge,Counter]]:
        """
        Collect and aggregate cached metrics from all configured collectors to be exported.
        """

        for collector in self.collectors:
            yield from collector.export_metrics()

    def collect(self) -> Iterator[Metric]:
        """
        Collect and yield cached metrics in the format expected by the Prometheus client registry for each collector.
        Called automatically by Prometheus on each scrape request.
        """

        for metric in self.export_metrics():
            yield from metric.collect()

    async def start_http_server(self, host:str, port:int) -> web.AppRunner:
        """
        Initializes and starts the aiohttp web server that exports Prometheus metrics from the collect() method
        at each scrape request on the /metrics endpoint to be ingested by Prometheus. The server listens on the specified host and port.
        """
        try:
            registry = CollectorRegistry()
            registry.register(self)
            app = web.Application()
            app.router.add_get("/metrics", make_aiohttp_handler(registry))
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, host, port)
            await site.start()
            log.info("Prometheus exporter serving on http://%s:%d/metrics", host, port)
            return runner
        except OSError as e:
            log.error("Failed to bind to %s:%d - %s", host, port, e)
            raise HTTPServerFailedException
        except Exception as e:
            log.error("Unexpected error starting HTTP server: %s", e)
            raise HTTPServerFailedException


async def main():
    parser = argparse.ArgumentParser(description="Azure Slurm Prometheus Exporter")
    parser.add_argument("--port", type=int, default=9101, help="Port to expose metrics on (default: 9101)")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to bind to (default: 0.0.0.0)")
    args = parser.parse_args()

    conf_file = resources.files("exporter").joinpath("exporter_logging.conf")
    logging.config.fileConfig(str(conf_file))

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    collector = CompositeCollector()

    try:
        collector.initialize_collectors()
    except NoCollectorsFoundException:
        sys.exit(1)

    runner = None
    try:
        runner = await collector.start_http_server(host=args.host, port=args.port)
    except HTTPServerFailedException:
        sys.exit(1)

    # Keep running until interrupted
    try:
        await stop_event.wait()
    except asyncio.CancelledError:
        pass
    finally:
        if runner:
            await runner.cleanup()