# Running integration tests

## Use example_props.json as a basic

You can either pull exactly the properties from an existing cluster via `cyclecloud export_parameters CLUSTER > p.json`
or you can use example_props.json to fill out the most basic information - mostly which region and subnet to use.

## Importing clusters
`python3 src/integration import -p props.json`

## Startings clusters
`python3 src/integration start [--skip-tests]`
Note you can skip the tests. This is useful when you are just testing the converge process on all platforms.

## Shutting down clusters
`python3 src/integration shutdown`
This shuts down the clusters, though it does not block.