#!/usr/bin/env bash
set -e

run_slurmdbd_via_systemctl() {

    echo "Starting slurmdbd via systemctl..."
    systemctl start slurmdbd

    # Verify slurmdbd is responding
    sleep 10
    if ! sacctmgr ping > /dev/null 2>&1; then
        echo "ERROR: slurmdbd started but is not responding to sacctmgr ping"
        exit 2
    fi
    echo "slurmdbd is running and responding to ping"
}

run_slurmdbd() {

    if [[ $(jetpack config slurm.is_primary_scheduler True) == "False" ]]; then
        run_slurmdbd_via_systemctl
        return
    fi
    # Get the slurm version from scontrol
    slurm_version=$(scontrol --version | awk '{print $2}')
    if [ -z "$slurm_version" ]; then
        echo "Failed to get slurm version from scontrol --version"
        return 1
    fi
    echo "Slurm version: $slurm_version"

    # Define the expected startup message
    startup_message="slurmdbd version ${slurm_version} started"
    echo "Waiting for startup message: $startup_message"

    # Create a temp file for slurmdbd output
    log_file=$(mktemp)

    # Start slurmdbd in foreground as user slurm, redirect output to log file
    # use setsid to start slurmdbd in a new session.
    setsid sudo -u slurm /usr/sbin/slurmdbd -D > "$log_file" 2>&1 &
    slurmdbd_pid=$!

    # Monitor the log file for the startup message.
    # slurmdbd rollup can take a long time. We are considering a timeout of 1 hr.
    timeout=3600
    elapsed=0
    started=false

    while [ $elapsed -lt $timeout ]; do
        if grep -q "$startup_message" "$log_file" 2>/dev/null; then
            echo "Detected slurmdbd startup message"
            started=true
            break
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done


    # Only kill the foreground process if started successfully
    if [ "$started" == "true" ]; then
        # Kill the foreground slurmdbd process
        if [ -n "$slurmdbd_pid" ] && kill -0 $slurmdbd_pid 2>/dev/null; then
            echo "Stopping foreground slurmdbd process (PID: $slurmdbd_pid)"
            kill -INT $slurmdbd_pid
            # Wait up to 60 seconds for graceful shutdown
            wait_timeout=60
            while [ $wait_timeout -gt 0 ] && kill -0 $slurmdbd_pid 2>/dev/null; do
                sleep 1
                wait_timeout=$((wait_timeout - 1))
            done

            # Force kill if still running
            if kill -0 $slurmdbd_pid 2>/dev/null; then
                echo "Process did not exit gracefully, sending SIGKILL"
                kill -9 $slurmdbd_pid 2>/dev/null
                sleep 1
            fi
            echo "Foreground slurmdbd process stopped"
        fi

        run_slurmdbd_via_systemctl
    else
        echo "slurmdbd startup is taking long, manual intervention is required"
    fi

    # clean up the log file
    rm -f "$log_file"
}

run_slurmctld() {
    echo "Starting Slurmctld"
    systemctl start slurmctld
    attempts=3
    delay=5
    set +e
    for i in $( seq 1 $attempts ); do
        echo $i/$attempts sleeping $delay seconds before running scontrol ping
        sleep $delay
        scontrol ping > /dev/null 2>&1;
        if [ $? == 0 ]; then
            systemctl start slurmctld || exit 1
            break
        fi;
    done
    if [ $i == $attempts ] && [ $? != 0 ]; then
        echo FATAL: slurmctld failed to start! 1>&2
        echo Here are the last 100 lines of slurmctld.log
        tail -n 100 /var/log/slurmctld/slurmctld.log 1>&2
        exit 2
    fi
}

run_slurmrestd() {
    if [[ "$OS" == "sle_hpc" ]]; then
        echo Warning: slurmrestd is not supported on SUSE, skipping start. 1>&2
        exit 0
    fi
    monitoring_enabled=$(/opt/cycle/jetpack/bin/jetpack config cyclecloud.monitoring.enabled False)
    systemctl start slurmrestd
    systemctl status slurmrestd --no-pager > /dev/null
    if [ $? != 0 ]; then
        echo Warning: slurmrestd failed to start! 1>&2
        /opt/cycle/jetpack/bin/jetpack log "slurmrestd failed to start" --level=warn --priority=medium
        exit 0
    fi
    # start slurm_exporter if monitoring is enabled and slurmrestd is running
    if [[ "$monitoring_enabled" == "True" ]]; then
        run_slurm_exporter
    fi
}

reload_prom_config(){
    # Find the Prometheus process and send SIGHUP to reload config or log a warning if not found
    if [[ "$monitoring_enabled" == "False" ]]; then
        echo "Monitoring is disabled, skipping Prometheus config reload"
        return 0
    fi
    PROM_PID=$(pgrep -f 'prometheus')
    if [ -n "$PROM_PID" ]; then
        echo "Sending SIGHUP to Prometheus (PID $PROM_PID) to reload configuration"
        kill -HUP $PROM_PID
    else
        echo "Prometheus process not found, unable to reload configuration"
    fi  
}

run_slurm_exporter() {
    # Run Slurm Exporter in a container
    if [[ "$role" != "scheduler" ]]; then
        echo "Slurm Exporter can only be run on the scheduler node, skipping setup."
        return 0
    fi

    primary_scheduler=$(/opt/cycle/jetpack/bin/jetpack config slurm.is_primary_scheduler True)
    if [[ "$primary_scheduler" != "True" ]]; then
        echo "This is not the primary scheduler, skipping slurm_exporter setup."
        return 0
    fi
    
    SLURM_EXPORTER_PORT=9200
    SLURM_EXPORTER_IMAGE_NAME="ghcr.io/slinkyproject/slurm-exporter:0.3.0"
    # Try to get the token, retry up to 3 times
    unset SLURM_JWT
    for attempt in 1 2 3; do
        export $(scontrol token username="slurmrestd" lifespan=infinite)
        if [ -n "$SLURM_JWT" ]; then
            break
        fi
        echo "Attempt $attempt: Failed to get SLURM_JWT token, retrying in 5 seconds..."
        scontrol reconfigure
        sleep 5
    done

    if [ -z "$SLURM_JWT" ]; then
        echo "Failed to get SLURM_JWT token after 3 attempts."
        echo "Check slurmctld status, slurm.conf JWT configuration, and logs for errors."
        /opt/cycle/jetpack/bin/jetpack log "Failed to get SLURM_JWT token after 3 attempts, disabling slurm_exporter setup." --level=warn --priority=medium
        return 0
    fi
    # Check if the container is already running, and if so, stop it
    if [ "$(docker ps -q -f ancestor=$SLURM_EXPORTER_IMAGE_NAME)" ]; then
        echo "Slurm Exporter is already running, stopping it..."
        docker stop $(docker ps -q -f ancestor=$SLURM_EXPORTER_IMAGE_NAME)
    fi

    # Run the Slurm Exporter container, expose the port so prometheus can scrape it. Redirect the host.docker.internal to the host gateway == localhost
    docker run -v /var:/var -e SLURM_JWT=${SLURM_JWT} -d --restart always -p ${SLURM_EXPORTER_PORT}:8080 --add-host=host.docker.internal:host-gateway $SLURM_EXPORTER_IMAGE_NAME -server http://host.docker.internal:6820 -cache-freq 10s

    # Check if the container is running
    if [ "$(docker ps -q -f ancestor=$SLURM_EXPORTER_IMAGE_NAME)" ]; then
        echo "Slurm Exporter is running"
    else
        echo "Slurm Exporter is not running"
        /opt/cycle/jetpack/bin/jetpack log "Slurm Exporter container failed to start" --level=warn --priority=medium
        return 0 # do not fail the slurm startup if exporter fails
    fi

    reload_prom_config
        
    sleep 20
    if curl -s http://localhost:${SLURM_EXPORTER_PORT}/metrics | grep -q "slurm_nodes_total"; then
        echo "Slurm Exporter metrics are available"
    else
        echo "Slurm Exporter metrics are not available"
        /opt/cycle/jetpack/bin/jetpack log "Slurm Exporter metrics are not available" --level=warn --priority=medium
    fi 
}


{ 
    if [ "$1" == "" ]; then
        echo "Usage: $0 [scheduler|execute|login]"
        exit 1
    fi

    role=$1

    OS=$(. /etc/os-release; echo $ID)
    echo "Starting services"
    # all nodes need to have munge running
    echo restarting munge...
    systemctl restart munge
    # wait up to 60 seconds for munge to start
    iters=60
    while [ $iters -ge 0 ]; do
        echo test | munge > /dev/null 2>&1
        if [ $? == 0 ]; then
            break
        fi
        sleep 1
        iters=$(( $iters - 1 ))
    done

    # login nodes explicitly should _not_ have slurmd running.
    if [ $role == "login" ]; then
        reload_prom_config
        exit 0
    fi

    # execute nodes just need slurmd
    if [ $role == "execute" ]; then
        systemctl start slurmd
        reload_prom_config
        exit 0
    fi

    # sanity check - make sure a valid role was actually passed in.
    # note they are defined in the slurm_*_role.rb
    if [ $role != "scheduler" ]; then
        echo  unknown role! $role 1>&2
        exit 2
    fi

    # lastly - the scheduler
    run_slurmdbd

    run_slurmctld

    run_slurmrestd
} 2>&1 | tee -a /var/log/azure-slurm-install.log
