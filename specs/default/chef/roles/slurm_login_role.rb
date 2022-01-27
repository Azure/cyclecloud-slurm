# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
name "slurm_login_role"
description "Slurm Login Role"
run_list("recipe[cyclecloud]",
  "recipe[cshared::client]",
  "recipe[cuser]",
  "recipe[slurm::login]")