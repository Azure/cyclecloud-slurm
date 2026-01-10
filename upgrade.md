# Cyclecloud Slurm Clusters Upgrade procedure

## Pre-upgrade

Slurm major version upgrade (from 24.x to 25.x) with job accounting enabled causes roll-up in the database. So the first step is to backup the database to persistent storage.

1. Create a backups directory on a persistent storage or use an existing one.

   On scheduler VM:
   ```
   mkdir -p /shared/cluster-backups
   ```

2. Stop slurmdbd

   ```
   systemctl stop slurmdbd
   ```

3. Take the dump of the database.

   Export db auth variables

   ```
   export $(cat /etc/slurm/slurmdbd.conf | grep Storage)
   ```
   
   ```
   mysqldump -h $StorageHost -u $StorageUser -p --databases $StorageLoc > /tmp/"$StorageLoc"_backup_"$(date +%Y_%m_%d)".sql
   ```

   - `db_hostname`: hostname of the azure mysql flex. This can be found in `/etc/slurm/slurmdbd.conf`
   - `dbuser`: user that can access database.

## Upgrade

Following steps need to be run on the CC VM.

4. Upgrade cyclecloud

   ```
   export VERSION_NUMBER=
   curl https://raw.githubusercontent.com/Azure/cyclecloud-slurm/refs/heads/upgrade_jan26/util/upgrade_cyclecloud.sh $VERSION_NUMBER | bash -
   ```
5. Scale down the cluster.

6. Terminate the cluster.

   This will not terminate persistent data on `/shared` and `/sched`.

7. Make Changes to the UI via the edit button:
   - Under the Required Settings Tab:
      1. Check Slurm HA Node box under High Availibility section
   - Under Network Attached Storage Tab
      1. Check the Add Shared Filesystem mount under Additional Filesystem Mount section
      2. Set FS Type to Azure Managed Lustre
      3. Fill in mount details
   - Under the Advanced Settings Tab:
      1. Change slurm version to `25.05.5`
      2. Set SSL Certificate URL under Slurm Settings as "https://cacerts.digicert.com/DigiCertGlobalRootG2.crt.pem"
      3. remove the monitoring cluster-init for all node-arrays.
   - Hit Save

8. Export cyclecloud cluster parameters

   On the cyclecloud VM:

   ```
   cyclecloud export_parameters $clustername -p params.json
   ```

   Verify the following:

   ```
   "configuration_slurm_version": "25.05.5"
   "configuration_slurm_ha_enabled": true
   ```

   Verify the accounting certificate for MySql Flex:

   ```
   "configuration_slurm_accounting_certificate_url": "https://cacerts.digicert.com/DigiCertGlobalRootG2.crt.pem"
   ```

   Verify monitoring cluster-init is not present in any node-array cluster-init specs.

9. Modify the template.

   - Add `cyclecloud.enable_chef = False` in the configuration section of the node defaults section in the slurm template.
   - Insert `[[[cluster-init cyclecloud/monitoring:default:1.0.5]]]` before `cyclecloud/slurm` cluster-init
   - Replace `cyclecloud/slurm` project version to `4.0.5`
   - Replace `cyclecloud/healthagent` project version to `1.0.4`

10. Import the cluster

   ```
   cyclecloud import_cluster -f slurm.txt -p params.json -c slurm $clustername --force
   ```

11. Start the Cluster



## Post-Upgrade

[On the Scheduler Node]

12. Once scheduler and scheduler HA node are back, verify functionality:

    ```
    sacctmgr ping
    scontrol ping
    sacct
    sinfo
    ```

13. Install scale_m1. (MUST run as root)

    ```
    curl https://raw.githubusercontent.com/Azure/cyclecloud-slurm/refs/heads/upgrade_jan26/util/install_scalem1.sh | bash -
    ```

## Notes (Optional if UI changes don't work)
Steps after step 6 from above.

7. Export cyclecloud cluster parameters

   On the cyclecloud VM:

   ```
   cyclecloud export_parameters $clustername -p params.json
   cp params.json params_backup.json
   ```

   In params.json, Remove all cluster-init projects for all node-array cluster-init specs and make the value `null`
   
   Modify the template.

   - Insert `[[[cluster-init cyclecloud/monitoring:default:1.0.5]]]` before `cyclecloud/slurm` cluster-init
   - Replace `cyclecloud/slurm` project version to `4.0.5`
   - Replace `cyclecloud/healthagent` project version to `1.0.4`

   Reimport the cluster with null cluster-init params.json and new template
   ```
   cyclecloud import_cluster -f slurm.txt -p params.json -c slurm $clustername --force
   ```
   Update the following in params_backup.json
      ```
      "configuration_slurm_version": "25.05.5"
      "configuration_slurm_ha_enabled": true
      ```
   In params_backup.json Remove the monitoring cluster-init from all node-array cluster-init specs
   ```
    "monitoring:default:1.0.0" : {
      "Order" : 10000,
      "Name" : "monitoring:default:1.0.0",
      "Spec" : "default",
      "Project" : "monitoring",
      "Version" : "1.0.0",
      "Locker" : "azure-storage"
    },
    ```
   If we wamt to include CCWS cluster-init, add the CCW cluster-init version to `2025.12.01` for all node-array cluster-init specs
   ```
       "ccw:default:2025.12.01" : {
      "Order" : 10100,
      "Spec" : "default",
      "Name" : "ccw:default:2025.12.01",
      "Project" : "ccw",
      "Locker" : "azure-storage",
      "Version" : "2025.12.01"
    }
    ```
    Verify the accounting certificate for MySql Flex:
   ```
   "configuration_slurm_accounting_certificate_url": "https://cacerts.digicert.com/DigiCertGlobalRootG2.crt.pem"
   ```
   Upload ccw cluster-init project to locker if needed
   ```
   git clone https://github.com/Azure/cyclecloud-slurm-workspace.git
   cd cyclecloud-slurm-workspace
   cyclecloud project upload "<locker name>"
   ```
   Reimport the cluster with updated params_backup.json and new template
   ```
   cyclecloud import_cluster -f slurm.txt -p params_backup.json -c slurm $clustername --force
   ```

