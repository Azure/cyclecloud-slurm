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

class BaseCollector(ABC):
    @abstractmethod
    async def start(self) -> None:
        """
        Begin collecting metrics asynchronously and runs it at regular
        intervals as defined by the configured downstream interval.
        """
        ...

    @abstractmethod
    def export_metrics(self) -> List[Union[Gauge,Counter,Summary]]:
        """
        Return metrics in Prometheus-compatible format.
        """
        ...

    async def run_command(self, *args, timeout=120,) -> CommandResult:
        """
        Executes a command asynchronously in a subprocess, capturing both stdout
        and stderr, with support for timeout handling.
        """
        start = time.monotonic()
        cmd_str = " ".join(str(a) for a in args)
        proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            async with asyncio.timeout(timeout):
                stdout, stderr = await proc.communicate()
        except TimeoutError:
            proc.kill()
            await proc.wait()
            log.error("Command: %s timed out after %d seconds and was killed", cmd_str, timeout)
            raise RuntimeError("Process timed out and was killed")
        elapsed = time.monotonic() - start
        log.debug("Command: %s, Exit code: %d, Time Elapsed: %f", cmd_str, proc.returncode, elapsed)
        if stderr:
            log.warning("stderr:\n%s", stderr.decode())
        return CommandResult(returncode=proc.returncode, stdout=stdout, stderr=stderr)

    def launch_task(self, func, interval) -> None:
        """
        Launch an asynchronous task that executes a callable function at regular intervals.
        """

        asyncio.create_task(self.__schedule(func, interval))

    async def __schedule(self, func, interval: int) -> None:
        """
        Schedule a callable function to be executed periodically at specified intervals.
        """
        if callable(func):
            reponse = await func()
            loop = asyncio.get_running_loop()
            loop.call_later(interval, partial(self.launch_task, func, interval))
        else:
            log.error(f"func {func.__name__} is not callable")

class AzslurmCollector:
    def __init__(self):
        self.collectors = []

    def initialize_collectors(self) -> None:
        """
        Initialize and start all collectors concurrently.
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
            log.error("No collectors intialized")
            raise NoCollectorsFoundException
        for collector in self.collectors:
            collector.start()

    def export_metrics(self) -> List[Union[Gauge,Counter,Summary]]:
        """
        Collect and aggregate metrics from all configured collectors.
        """

        metrics = []
        for collector in self.collectors:
            metrics.extend(collector.export_metrics())
        return metrics

    def collect(self) -> Iterator[Metric]:
        """
        Collect and yield Prometheus metrics every scrape interval
        """

        metrics = self.export_metrics()
        for metric in metrics:
            yield from metric.collect()

    async def start_http_server(self, host:str, port:int) -> web.AppRunner:
        """
        Initializes and starts an aiohttp web server that
        exposes Prometheus metrics on the /metrics endpoint. The server listens on
        the specified host and port.
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

    collector = AzslurmCollector()

    try:
        collector.initialize_collectors()
    except NoCollectorsFoundException:
        sys.exit(1)

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
        await runner.cleanup()