name "slurm_execute_role"
description "Slurm Execute Role"
run_list("recipe[cyclecloud]",
  "recipe[cshared::client]",
  "recipe[cuser]",
  "recipe[slurm::execute]",
  "recipe[cganglia::client]")