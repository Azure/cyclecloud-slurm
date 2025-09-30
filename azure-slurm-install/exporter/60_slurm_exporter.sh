#!/bin/bash
set -e
script_dir="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROM_CONFIG=/opt/prometheus/prometheus.yml

SLURM_EXPORTER_PORT=9080

SLURM_EXPORTER_REPO="https://github.com/SlinkyProject/slurm-exporter.git"
SLURM_EXPORTER_COMMIT="478da458dd9f59ecc464c1b5e90a1a8ebc1a10fb"
SLURM_EXPORTER_IMAGE_NAME="ghcr.io/slinkyproject/slurm-exporter:0.3.0"

function is_scheduler() {
    jetpack config slurm.role | grep -q 'scheduler'
}
# Only install Slurm Exporter on Scheduler
if ! is_scheduler ; then
    echo "Do not install the Slurm Exporter since this is not the scheduler."
    exit 0
fi

echo "Installing Slurm Exporter..."

# Function to build the slurm exporter
# This is not used anymore, but kept for reference as we are using the docker conatainer
build_slurm_exporter() {
    # This function is not used anymore, but kept for reference
    echo "Building Slurm Exporter..."
    . /etc/os-release
    case $ID in
        ubuntu)
            DEBIAN_FRONTEND=noninteractive apt-get install -y git golang-go
            ;;
        rocky|almalinux|centos)
            dnf install -y git golang-go
            ;;
        *)
            echo "Unsupported OS: $ID"
            exit 1
            ;;
    esac

    # Build the exporter
    pushd /tmp
    rm -rf slurm-exporter
    git clone ${SLURM_EXPORTER_REPO}
    cd slurm-exporter

    # Pin the build to specific commit
    git checkout ${SLURM_EXPORTER_COMMIT}

    # Equivalent to:  docker build . -t slinky.slurm.net/slurm-exporter:0.3.0
    # "all" requires helm
    make docker-bake
    popd
}

run_slurm_exporter() {

    # Run Slurm Exporter in a container
    unset SLURM_JWT
    export $(scontrol token username="slurmrestd" lifespan=infinite)
    # Check if the token is set
    if [ -z "$SLURM_JWT" ]; then
        echo "Failed to get SLURM_JWT token - restarting slurm"
        systemctl restart slurmctld
        unset SLURM_JWT
        export $(scontrol token username="slurmrestd" lifespan=infinite)
        if [ -z "$SLURM_JWT" ]; then
            echo "Failed to get SLURM_JWT token after restarting slurm"
            exit 1
        fi
    fi

    # Check if the container is already running, and if so, stop it
    if [ "$(docker ps -q -f ancestor=$SLURM_EXPORTER_IMAGE_NAME)" ]; then
        echo "Slurm Exporter is already running, stopping it..."
        docker stop $(docker ps -q -f ancestor=$SLURM_EXPORTER_IMAGE_NAME)
    fi

    # Run the Slurm Exporter container, expose the port so prometheus can scrape it. Redirect the host.docker.internal to the host gateway == localhost
    docker run -v /var:/var -e SLURM_JWT=${SLURM_JWT} -d --restart always -p 9080:8080 --add-host=host.docker.internal:host-gateway $SLURM_EXPORTER_IMAGE_NAME -server http://host.docker.internal:6820 -cache-freq 10s

    # Check if the container is running
    if [ "$(docker ps -q -f ancestor=$SLURM_EXPORTER_IMAGE_NAME)" ]; then
        echo "Slurm Exporter is running"
    else
        echo "Slurm Exporter is not running"
        exit 1
    fi
}

function add_scraper() {
    if [ ! -f "$PROM_CONFIG" ]; then
        echo "Prometheus config file not found at $PROM_CONFIG, skipping scraper configuration"
        return 0
    fi
    # If slurm_exporter is already configured, do not add it again
    if grep -q "slurm_exporter" $PROM_CONFIG; then
        echo "Slurm Exporter is already configured in Prometheus"
        return 0
    fi
    INSTANCE_NAME=$(hostname)

    yq eval-all '. as $item ireduce ({}; . *+ $item)' $PROM_CONFIG $script_dir/slurm_exporter.yml > tmp.yml
    mv -vf tmp.yml $PROM_CONFIG

    # update the configuration file
    sed -i "s/instance_name/$INSTANCE_NAME/g" $PROM_CONFIG

    systemctl restart prometheus
}

if is_scheduler ; then
    run_slurm_exporter
    add_scraper

    # Check if metrics are available, can only be done after prometheus has been configured and restarted
    # we need to wait a bit for prometheus to start and scrape the metrics
    sleep 20
    if curl -s http://localhost:${SLURM_EXPORTER_PORT}/metrics | grep -q "slurm_nodes_total"; then
        echo "Slurm Exporter metrics are available"
    else
        echo "Slurm Exporter metrics are not available"
        exit 1
    fi    
fi