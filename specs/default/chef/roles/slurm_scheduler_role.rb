# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
name "slurm_scheduler_role"
description "Slurm Scheduler Role"
run_list("role[scheduler]",
  "recipe[cyclecloud]",
  "recipe[cshared::directories]",
  "recipe[cuser]",
  "recipe[cshared::server]",
  "recipe[slurm::scheduler]",
  "recipe[cganglia::server]")
default_attributes "cyclecloud" => { "discoverable" => true }
