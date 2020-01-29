# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
name "slurm_master_role"
description "Slurm Master Role"
run_list("role[scheduler]",
  "recipe[cyclecloud]",
  "recipe[cshared::directories]",
  "recipe[cshared::server]",
  "recipe[slurm::scheduler]")
default_attributes "cyclecloud" => { "discoverable" => true }
