from slurmcc import util
from slurmcc_test import testutil




def test_parse_show_nodes() -> None:
    recs = util.parse_show_nodes("""
NodeName=s301-c7-dynamic-7 Arch=x86_64 CoresPerSocket=1 
   CPUAlloc=0 CPUEfctv=2 CPUTot=2 CPULoad=0.22
   AvailableFeatures=dyn
   ActiveFeatures=dyn
   Gres=(null)
   NodeAddr=10.1.0.7 NodeHostName=s301-c7-dynamic-7 Version=22.05.8
   OS=Linux 3.10.0-1127.19.1.el7.x86_64 #1 SMP Tue Aug 25 17:23:54 UTC 2020 
   RealMemory=3072 AllocMem=0 FreeMem=1588 Sockets=1 Boards=1
   State=IDLE+DYNAMIC_NORM+POWERED_DOWN ThreadsPerCore=2 TmpDisk=0 Weight=1 Owner=N/A MCS_label=N/A
   Partitions=dynamic 
   BootTime=2023-03-21T19:46:44 SlurmdStartTime=2023-03-21T20:27:08
   LastBusyTime=Unknown
   CfgTRES=cpu=2,mem=3G,billing=2
   AllocTRES=
   CapWatts=n/a
   CurrentWatts=0 AveWatts=0
   ExtSensorsJoules=n/s ExtSensorsWatts=0 ExtSensorsTemp=n/s

NodeName=d1 CoresPerSocket=1 
   CPUAlloc=0 CPUEfctv=1 CPUTot=1 CPULoad=N/A
   AvailableFeatures=dyn,standard_f4
   ActiveFeatures=dyn,standard_f4
   Gres=(null)
   NodeAddr=d1 NodeHostName=d1 
   RealMemory=1 AllocMem=0 FreeMem=N/A Sockets=1 Boards=1
   State=IDLE+CLOUD+DYNAMIC_NORM+NOT_RESPONDING+POWERING_UP ThreadsPerCore=1 TmpDisk=0 Weight=1 Owner=N/A MCS_label=N/A
   Partitions=dynamic 
   BootTime=None SlurmdStartTime=None
   LastBusyTime=2023-03-27T17:53:40
   CfgTRES=cpu=1,mem=1M,billing=1
   AllocTRES=
   CapWatts=n/a
   CurrentWatts=0 AveWatts=0
   ExtSensorsJoules=n/s ExtSensorsWatts=0 ExtSensorsTemp=n/s""")

    assert len(recs) == 2
    assert recs[0]["NodeName"] == "s301-c7-dynamic-7"
    assert recs[0]["State"] == "IDLE+DYNAMIC_NORM+POWERED_DOWN"
    assert recs[1]["NodeName"] == "d1"
    assert recs[1]["State"] == "IDLE+CLOUD+DYNAMIC_NORM+NOT_RESPONDING+POWERING_UP"