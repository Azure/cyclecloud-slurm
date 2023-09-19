# Running the integration tests

## Prerequisites
Make sure `cyclecloud` is in your path and is working.

Highly recommended that you have `$CS_HOME` defined as well.

Lastly, I recommend you clear our `$CS_HOME/work/staging/projects/slurm` so that the latest artifacts are 
downloaded from GitHub.

## Create a parameters json file
We need some common parameters for your clusters. Save these as `integration/params.json`, filling in the values 
with `{}`

```json
{
  "UsePublicNetwork" : false,
  "Region" : "{myregion}",
  "NumberLoginNodes" : 1,
  "Credentials" : "{mycred, probably cloud}",
  "ExecuteNodesPublic" : false,
  "SubnetId" : "{my-persisten-rg}/{myvnet}/default",
  "ReturnProxy" : false
}
```

## Create an NFS cluster
You need to create an NFS cluster, as most of our integration tests require this. You
can set this up separately, but there is a handy command to do this automatically. Note that you
need CS_HOME defined.

```bash
python3 src/integration.py setup_nfs -p params.json
```

Otherwise, make sure that `/sched` and `/shared` are exported and restart `nfs-mountd`.

```bash
echo '/mnt/exports/sched *(rw,sync,no_root_squash)' >> /etc/exports
echo '/mnt/exports/shared *(rw,sync,no_root_squash)' >> /etc/exports
systemctl restart nfs-mountd
```


### Import the clusters

```bash
$ python3 src/integration.py import -p param.json
# Note pass in -n {nfs instance ip address} if you are using your own NFS instance
```

<details>
<summary>--help</summary>

```bash
$ python3 src/integration.py import --help
usage: integration.py import [-h] [--skip-stage-resources] --properties PROPERTIES --nfs-address NFS_ADDRESS

optional arguments:
  -h, --help            show this help message and exit
  --skip-stage-resources
  --properties PROPERTIES, -p PROPERTIES
  --nfs-address NFS_ADDRESS, -n NFS_ADDRESS
```

Only use `--skip-stage-resources` when you are running these before a GitHub release is available.
</details>



### Start the clusters
There is a command for starting _all_ of the tests, or you can start them manually with `cyclecloud start_cluster`

```bash
$ python3 src/integration.py start
```

To start just a single cluster
```bash
cyclecloud start_cluster {cluster_name} --test
```

<details>
<summary>--help</summary>

```bash
$ python3 src/integration.py start --help
usage: integration.py start [-h] [--skip-tests]

optional arguments:
  -h, --help    show this help message and exit
  --skip-tests

$ python3 src/integration.py start
```
</details>

### Shutdown and delete the clusters
Note that unless you pass in `--include-nfs`, the `integration-nfs` cluster will not be shutdown/deleted.
```bash
$ python3 src/integration.py shutdown [--include-nfs]
$ python3 src/integration.py delete [--include-nfs]
```