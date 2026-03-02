import asyncio
import logging
import signal
import sys
import time
from prometheus_client import CollectorRegistry, Metric, Counter, Gauge, Summary
from abc import ABC, abstractmethod
from functools import partial
from collections import namedtuple
from aiohttp import web
from prometheus_client.aiohttp import make_aiohttp_handler
from typing import Iterator, List, Union

log = logging.getLogger(__name__)
CommandResult = namedtuple("CommandResult", ["returncode", "stdout", "stderr"])

class NoCollectorsFoundException(Exception):
    pass

class HTTPServerFailedException(Exception):
    pass

class BaseCollector(ABC):
    @abstractmethod
    async def start(self) -> None:
        """
        Begin collecting metrics asynchronously.

        This method initializes the metric collection process and runs it at regular
        intervals as defined by the configured downstream interval. The collection
        runs asynchronously without blocking the event loop.
        """
        ...

    @abstractmethod
    def export_metrics(self) -> List[Union[Gauge,Counter,Summary]]:
        """
        Return metrics in Prometheus-compatible format.

        Returns:
            list: A list of metric objects in Prometheus-compatible format,
                  ready for exposition to monitoring backends.
        """
        ...

    async def run_command(self, *args, timeout=120,) -> CommandResult:
        """
        Execute a command asynchronously and capture its output.

        This method runs an external command in a subprocess, capturing both stdout
        and stderr, with support for timeout handling.

        Args:
            *args: Command and arguments to execute. Each argument is converted to string.
            timeout (int, optional): Maximum time in seconds to wait for command completion.
                Defaults to 120 seconds.

        Returns:
            CommandResult: An object containing:
                - returncode (int): The exit code of the process
                - stdout (bytes): The standard output of the command
                - stderr (bytes): The standard error output of the command

        Raises:
            RuntimeError: If the command exceeds the specified timeout duration.
                The process is terminated before raising this exception.
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
        Launch an asynchronous task that executes a function at regular intervals.

        Args:
            func: A callable function to be executed repeatedly.
            interval: The time interval (in seconds) between successive executions of the function.
        """

        asyncio.create_task(self.__schedule(func, interval))

    async def __schedule(self, func, interval: int) -> None:
        """
        Schedule a function to be executed periodically at specified intervals.

        Args:
            func: A callable function to be scheduled for execution.
            interval (int): The time interval in seconds between function executions.

        Notes:
            - This is an async method that executes the function once immediately,
              then schedules subsequent executions using asyncio's call_later.
            - The function is executed in a non-blocking manner using asyncio.
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

        Attempts to initialize three types of collectors in sequence:
        - Squeue: Collects job queue information
        - Sacct: Collects job accounting data
        - Sinfo: Collects node/partition information

        Each collector is independently initialized and added to the collectors list
        if available. If a collector is not available, a warning is logged and the
        initialization continues with the next collector.

        Raises:
            NoCollectorsFoundException: If no collectors were successfully initialized.
        """
        try:
            from squeue import Squeue, SqueueNotAvailException
            squeue = Squeue()
            squeue.initialize()
        except SqueueNotAvailException:
            log.warning("squeue is not available, disabling squeue metrics")
        else:
            self.collectors.append(squeue)

        try:
            from sacct import Sacct, SacctNotAvailException
            sacct = Sacct()
            sacct.initialize()
        except SacctNotAvailException:
            log.warning("Accounting is disabled, disabling sacct metrics")
        else:
            self.collectors.append(sacct)

        try:
            from sinfo import Sinfo, SinfoNotAvailException
            sinfo = Sinfo()
            sinfo.initialize()
        except SinfoNotAvailException:
            log.warning("sinfo is not available, disabling sinfo metrics")
        else:
            self.collectors.append(sinfo)

        if not self.collectors:
            log.error("No collectors intialized")
            raise NoCollectorsFoundException
        for collector in self.collectors:
            collector.start()

    def export_metrics(self) -> List[Union[Gauge,Counter,Summary]]:
        """
        Collect and aggregate metrics from all configured collectors.

        Iterates through ``self.collectors``, calls each collector's
        ``export_metrics()`` method, and combines all returned metric items
        into a single list.

        Returns:
            list: A flattened list containing metric objects from every collector.
        """

        metrics = []
        for collector in self.collectors:
            metrics.extend(collector.export_metrics())
        return metrics

    def collect(self) -> Iterator[Metric]:
        """
        Collect and yield Prometheus metrics.

        This method retrieves exported metrics and iterates through them,
        yielding collected metric samples for each metric object.

        Yields:
            Metric samples from each exported metric's collect() method.
        """

        metrics = self.export_metrics()
        for metric in metrics:
            yield from metric.collect()

    async def start_http_server(self, host, port) -> web.AppRunner:
        """
        Start an HTTP server for Prometheus metrics collection.

        This asynchronous method initializes and starts an aiohttp web server that
        exposes Prometheus metrics on the /metrics endpoint. The server listens on
        the specified host and port.
        Args:
            host (str): The host address to bind the server to (e.g., '0.0.0.0').
            port (int): The port number to listen on (e.g., 9101).

        Returns:
            web.AppRunner: The runner object for the started HTTP server, which can
                           be used to manage the server lifecycle.

        Raises:
            HTTPServerFailedException: Raised if the server fails to bind to the
                                       specified host and port (OSError) or if any
                                       unexpected error occurs during server startup.

        Note:
            The server registers the current instance as a Prometheus collector
            to expose metrics. After calling this method, metrics will be available
            at at http://{host}:{port}/metrics.
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
    #TODO: file based logging 
    logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(name)s %(levelname)s %(message)s"
    )
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
        runner = await collector.start_http_server(host="0.0.0.0", port=9101)
    except HTTPServerFailedException:
        sys.exit(1)

    # Keep running until interrupted
    try:
        await stop_event.wait()
    except asyncio.CancelledError:
        pass
    finally:
        await runner.cleanup()

if __name__=="__main__":
    asyncio.run(main())