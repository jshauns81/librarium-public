# Public CI runs on GitHub-hosted Ubuntu 24.04

Every workflow job that executes steps pins `runs-on: ubuntu-24.04`, including
the jobs used by manual beta publication and promotion. The CI policy rejects
runner expressions, label lists and runner groups. The repository variable
previously used to select a runner no longer affects execution.
