# Cyclecloud Slurm Clusters Upgrade procedure


## Pre- upgrade

Slurm major version upgrade (from 24.x to 25.x) with job accounting enabled causes roll-up in the database. So the first step is to backup the database to persistent storage.


1. [OPTIONAL] Create a backups directory on a persistent storage or use an existing one.

On scheduler VM:
`mkdir -p /shared/cluster-backups`

2. Stop slurmdbd
    `systemctl stop slurmdbd`
3. Take the dump of the database.

`mysqldump -h $db_hostname -u $dbuser -p --databases $clustername_acct_db > /tmp/$clustername_acct_db_backup_jan6.sql`

dbhostname: hostname of the azure mysql flex. This can be found in /etc/slurm/slurmdbd.conf
dbuser: user that can access database.

4. Export cyclecloud cluster parameters

On the cyclecloud VM:

`cyclecloud export_parameters $clustername -p params.json`

Update the following:

`"configuration_slurm_version": 25.05.5`
`"configuration_slurm_ha_enabled": true`

Verify the accounting certificate for MySql Flex:

`"configuration_slurm_accounting_certificate_url" : "https://cacerts.digicert.com/DigiCertGlobalRootG2.crt.pem"`

5. Modify the template.

Replace cyclecloud/slurm project version to 4.0.5
        cyclecloud/healthagent project version to 1.0.4
        cyclecloud/monitoring project version to 1.0.5



6. `cyclecloud import_cluster -f slurm.txt -p params.json -c slurm $clustername --force`

7. Scale down the cluster.

8. terminate and restart the cluster.

This will not terminate persistent data on /shared and /sched.

9. Once scheduler and scheduler HA node are back.

Verify functionality:

`sacctmgr ping`
`scontrol ping`
`sacct` and `sinfo` should work correctly.

10. Install scale_m1.
(MUST run as root)

