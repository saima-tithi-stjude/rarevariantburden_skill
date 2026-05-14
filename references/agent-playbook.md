# RareVariantBurden Agent Playbook

Concise decision rules for operating `nf-core/rarevariantburden`.

---

## Pre-flight Checklist

Before launching, confirm every item below is satisfied. Fail fast if not.

| # | Check | Action if missing |
|---|---|---|
| 1 | Local pipeline repo exists and contains main.nf | Clone: `git clone https://github.com/nf-core/rarevariantburden.git` |
| 10 | Joint-called VQSR VCF exists | Ask user for correct path |
| 2 | VCF index (.tbi or .csi) exists | Run: `tabix -p vcf <vcf.gz>` |
| 3 | Case samples file exists and is non-empty | Ask user to provide file |
| 4 | Control data folder exists and is non-empty | Download from S3 (see below) |
| 5 | Reference matches gnomAD version | GRCh37 → v2exome; GRCh38 → v4exome or v4genome |
| 6 | Annotation folder present (annovar or vep) | Download from S3 (see below) |
| 7 | Java ≥ 17 present | `module load java/17` or install |
| 8 | Nextflow accessible | `module load nextflow` or conda env |
| 9 | Profile tools present (docker/singularity/conda) | Install/load before `--run` |

---

## Control Data Download Commands

```bash
# GRCh37 controls
aws s3 cp s3://cocorv-resource-files/gnomADv2exome/ /local/gnomADv2exome/ --recursive

# GRCh38 exome controls
aws s3 cp s3://cocorv-resource-files/gnomADv4.1exome/ /local/gnomADv4.1exome/ --recursive

# GRCh38 genome controls
aws s3 cp s3://cocorv-resource-files/gnomADv4.1genome/ /local/gnomADv4.1genome/ --recursive

# Annotation resources
aws s3 cp s3://cocorv-resource-files/annovarFolder/ /local/annovar/ --recursive
aws s3 cp s3://cocorv-resource-files/vepFolder/ /local/vep/ --recursive

# List all available resources
aws s3 ls s3://cocorv-resource-files/
```

---

## Reference / gnomAD Version Matrix

| `--reference` | Valid `--gnomad-version` | Control dataset |
|---|---|---|
| GRCh37 | v2exome | gnomAD v2 exome |
| GRCh38 | v4exome | gnomAD v4.1 exome |
| GRCh38 | v4genome | gnomAD v4.1 genome |

Mixing incompatible reference/version pairs causes the validation to fail immediately.

---

## Standard Workflow Sequence

```
validate_inputs()
  → ensure_runtime_tools()
  → ensure_dependency_tools()
  → write_params_file()
  → write_launch_script()
  → [dry-run: stop here]
  → execute_launch()
```

---

## Dry-Run First

Always run with `--dry-run` in a new environment:

```bash
python scripts/run_rarevariantburden.py \
  --repo-path /path/to/rarevariantburden \
  --case-vcf /path/to/joint.vcf.gz \
  --case-samples /path/to/samples.txt \
  --control-data-folder /path/to/gnomADv4.1exome \
  --outdir /path/to/output \
  --reference GRCh38 \
  --gnomad-version v4exome \
  --annovar-folder /path/to/annovar \
  --profile singularity \
  --dry-run
```

---

## Executor Selection

| Environment | `--executor` | Submission command |
|---|---|---|
| Local workstation | `local` | `bash run_rarevariantburden.local.sh` |
| IBM LSF cluster | `lsf` | `bsub < run_rarevariantburden.lsf.sh` |
| SLURM cluster | `slurm` | `sbatch run_rarevariantburden.slurm.sh` |
| PBS/Torque cluster | `pbs` | `qsub run_rarevariantburden.pbs.sh` |
| SGE cluster | `sge` | `qsub run_rarevariantburden.sge.sh` |

---

## Triage Order for Failures

1. Validation error in helper → fix inputs and rerun
2. Nextflow not found → check conda env or `module load nextflow`
3. Submission failure → check queue/account/resources; inspect stderr
4. Pipeline crash → check `.nextflow.log` in outdir
5. Task-level failure → check `pipeline_info/` logs, then `work/<hash>/` task directory
6. Missing outputs → check MultiQC report and `cocorv/`, `annotation/`, `qc/` subdirs

---

## Key nf-core Reminders

- **Always use `--repo-path`**. The pipeline is in development and cannot be run with `nextflow run nf-core/rarevariantburden`. Always point to a local clone.
- Clone command: `git clone https://github.com/nf-core/rarevariantburden.git`

## Runtime Resolution Order

The helper resolves nextflow/java automatically in this order:

| Step | Condition | Action |
|---|---|---|
| 1 | `--use-current-path` set | Skip conda entirely, trust current PATH |
| 2 | Conda env `--conda-env` found | Use it; resolve `nextflow` from its `bin/` |
| 3 | `--create-conda-env` set, env missing | Create env from `nextflow-env.yml`, then use |
| 4 | Conda env not found, no `--create-conda-env` | **Fall back to PATH**: check `nextflow` + `java >= 17` |
| 4a | PATH has both | Log resolved paths and continue normally |
| 4b | PATH missing one or both | Warn (dry-run) or fail with remediation steps (run mode) |

## Singularity Cache

Pass `--singularity-cache <dir>` to set `NXF_SINGULARITY_CACHEDIR`. The helper:
- Exports it into the **current process** environment so local Nextflow subprocess inherits it.
- Writes `export NXF_SINGULARITY_CACHEDIR=...` into the **generated launch script** for scheduler jobs.

Example:
```
--singularity-cache /research/rgs01/home/clusterHome/stithi/singularity-cache
```

- Do NOT use `-c` for pipeline parameters. Use `--params-file` or CLI `--param value`.
- Do NOT invent parameter names. See `nextflow_schema.json` or `references/config-and-output.md` for valid params.
- Use `-resume` to restart from the last successful checkpoint.
- Annotation tool parameter in the pipeline is `annovarFolder`. Use `--annovarFolder` or `annovarFolder:` in a params YAML.
