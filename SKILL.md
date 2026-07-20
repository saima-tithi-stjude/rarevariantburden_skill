---
name: rarevariantburden
description: |
  Use this skill when an agent needs to run, validate, troubleshoot, or explain the nf-core/rarevariantburden (CoCoRV-nf) pipeline for rare variant burden testing. This skill handles input validation, samplesheet-equivalent parameter generation, helper-driven Nextflow launch, scheduler submission, and output triage. Trigger this skill whenever a user mentions rare variant burden test, CoCoRV, rarevariantburden, gnomAD burden analysis, case-only variant analysis, VCF burden testing, or wants to run/configure/troubleshoot any nf-core rare variant pipeline. Also trigger when the user mentions jointly-called VCF files, VQSR, gnomAD control data, ANNOVAR, VEP annotation, or ethnicity-stratified variant analysis in a pipeline context.
argument-hint: |
  Provide: --repo-path (local clone of the pipeline repo), --case-vcf (joint-called VQSR VCF, or NA when using --case-vcf-file-list), --case-samples (sample ID text file), --control-data-folder, --outdir, and one of --reference GRCh37/GRCh38.
  Skip-ahead (pre-computed): --case-vcf-file-list, --case-normalized-vcf-file-list, --case-annotated-vcf-file-list, --case-genotype-gds-file-list + --case-annotation-gds-file-list (paired), --case-population.
  Optional: --annovar-folder, --vep-folder, --gnomad-version, --annotation-tool, --chr-set, --af-max, --acan-config, --variant-exclude, --profile, --executor, --dry-run/--run.
user-invocable: true
version: 1.0.0
license: MIT
compatibility:
  python: ">=3.9"
---

# RareVariantBurden Pipeline Skill

## Overview

This skill defines how an agent executes **nf-core/rarevariantburden** (CoCoRV-nf) — a pipeline for
consistent summary count-based rare variant burden testing. It is designed for case-only studies
where matched control data is unavailable; pre-processed gnomAD public summary counts serve as
controls.

The helper entrypoint is:
- `scripts/run_rarevariantburden.py`

The agent MUST use this helper for validation, artifact generation, and launch logic.
Do NOT bypass it with manually assembled `nextflow run` commands.

## When To Use

Use this skill when the user wants to:
- Run a rare variant burden test from a joint-called VCF against gnomAD controls
- Validate inputs (case VCF, sample list, control data, annotation resources)
- Generate or fix pipeline parameters and launch artifacts
- Run locally or submit to LSF / Slurm / PBS / SGE
- Perform dry-run validation before execution
- Troubleshoot failures and interpret outputs (QQ plots, FDR results, top-K gene lists)

Do NOT use this skill for:
- Clinical interpretation of burden test results beyond basic sanity checks
- Modifying nf-core/rarevariantburden pipeline internals unless explicitly requested
- Variant calling upstream steps (use nf-core/sarek for that)

## Pipeline Summary

nf-core/rarevariantburden performs:
1. Chromosome-wise splitting of joint-called VQSR VCF (BCFtools)
2. Normalization and QC of split VCF files (BCFtools)
3. Annotation with ANNOVAR (default), VEP, or ANNOVAR_VEP
4. GDS format conversion (R seqarray)
5. Ethnicity prediction via gnomAD random forest classifier
6. CoCoRV association test per chromosome
7. Result merging
8. FDR calculation, QQ plot, and lambda estimation
9. Top-K gene variant/sample list generation

## Minimal Required Inputs

| Parameter | Description |
|---|---|
| `--repo-path` | Local path to the cloned pipeline repo (contains main.nf) |
| `--case-vcf` | Joint-called and VQSR-applied VCF (.vcf.gz). Set to `NA` when using `--case-vcf-file-list`. |
| `--case-samples` | Text file with one sample ID per line |
| `--control-data-folder` | Local path to downloaded gnomAD control data |
| `--outdir` | Output directory |
| `--reference` | `GRCh37` or `GRCh38` |

## Skip-Ahead Inputs (Pre-Computed Intermediates)

Supply any of these to skip earlier pipeline stages. Each (except `--case-population`) is a CSV file with a header row. `--case-genotype-gds-file-list` and `--case-annotation-gds-file-list` must always be provided together.

| Parameter | CSV columns | Skips |
|---|---|---|
| `--case-vcf-file-list` | `chr,vcf` | `splitJointVCF`. Requires `--case-vcf NA`. |
| `--case-normalized-vcf-file-list` | `chr,vcf,index` | `normalizeQC`. Requires `--case-vcf-file-list`. |
| `--case-annotated-vcf-file-list` | `chr,vcf,index` | ANNOVAR/VEP annotation entirely. |
| `--case-genotype-gds-file-list` | `chr,gds` | `caseGenotypeGDS` conversion. Paired with below. |
| `--case-annotation-gds-file-list` | `chr,gds` | `caseAnnotationGDS` conversion. Paired with above. |
| `--case-population` | (plain file path, not CSV) | gnomAD extraction, merging, RF prediction. |

## Control Data Download

Control datasets are hosted on S3. Download with aws-cli before running:

```bash
# gnomAD v2 exome (GRCh37)
aws s3 cp s3://cocorv-resource-files/gnomADv2exome/ /local/control/ --recursive

# gnomAD v4.1 exome (GRCh38)
aws s3 cp s3://cocorv-resource-files/gnomADv4.1exome/ /local/control/ --recursive

# gnomAD v4.1 genome (GRCh38)
aws s3 cp s3://cocorv-resource-files/gnomADv4.1genome/ /local/control/ --recursive

# Annotation resources
aws s3 cp s3://cocorv-resource-files/annovarFolder/ /local/annovar/ --recursive
aws s3 cp s3://cocorv-resource-files/vepFolder/ /local/vep/ --recursive
```

## Quick Start

Dry-run (validate only):

```bash
python scripts/run_rarevariantburden.py \
  --repo-path /path/to/rarevariantburden \
  --case-vcf /path/to/joint.vcf.gz \
  --case-samples /path/to/samples.txt \
  --control-data-folder /path/to/gnomADv4.1exome \
  --outdir /path/to/output \
  --reference GRCh38 \
  --gnomad-version v4exome \
  --annovar-folder /path/to/annovarFolder \
  --profile singularity \
  --dry-run
```

Scheduler run (Slurm):

```bash
python scripts/run_rarevariantburden.py \
  --repo-path /path/to/rarevariantburden \
  --case-vcf /path/to/joint.vcf.gz \
  --case-samples /path/to/samples.txt \
  --control-data-folder /path/to/gnomADv4.1exome \
  --outdir /path/to/output \
  --reference GRCh38 \
  --gnomad-version v4exome \
  --annovar-folder /path/to/annovarFolder \
  --profile singularity \
  --executor slurm \
  --queue compute \
  --project my_account \
  --cpus 16 \
  --memory-gb 64 \
  --walltime 48:00 \
  --run
```

## Workflow

1. Validate required user inputs (local repo path, VCF, samples file, control folder, outdir, reference).
   Fail immediately if --repo-path does not exist or does not contain main.nf.
2. Validate file paths exist locally (VCF index .tbi/.csi checked, samples file, control folder).
3. Validate reference/gnomAD version compatibility (`GRCh37` → `v2exome`; `GRCh38` → `v4exome` or `v4genome`).
4. Resolve runtime settings (profile, executor, resources).
5. Call `scripts/run_rarevariantburden.py` to generate params YAML and launch script.
6. Stop for dry-run: if `--dry-run` without `--run`, stop after validation and artifact generation.
7. Execute only in run mode: if `--run`, execute locally or submit via selected executor.
8. Report run status, scheduler job ID if available, and first triage targets.

## Operational Guidance

- Use `--dry-run` before the first execution in a new environment.
- Use `--gnomad-version v2exome` only with `--reference GRCh37`.
- Use `--gnomad-version v4exome` or `--gnomad-version v4genome` with `--reference GRCh38`.
- Default annotation tool is ANNOVAR. Use `--annotation-tool VEP` to switch to VEP.
- Always provide `--repo-path` pointing to a local clone of the repository. The pipeline is in
  development and cannot be invoked via the `nf-core/rarevariantburden` shorthand.
- Clone command: `git clone https://github.com/nf-core/rarevariantburden.git`
- **Runtime resolution order** (automated):
  1. `--use-current-path`: skip conda entirely, trust current PATH.
  2. Conda env `--conda-env` found: use it, resolve `nextflow` from its `bin/`.
  3. `--create-conda-env`: create the conda env from `environment/nextflow-env.yml`, then use it.
  4. Conda env not found and no `--create-conda-env`: **fall back to PATH** — if `nextflow` and
     `java >= 17` are both on PATH, continue; otherwise warn (dry-run) or fail (run mode).
- For `--singularity-cache`: the path is exported as `NXF_SINGULARITY_CACHEDIR` both into the
  current process environment (for local runs) and into the generated launch script (for scheduler
  submissions). Provide an absolute path to a shared directory for image caching.
- Use `--chr-set` to restrict processing to a subset of chromosomes (e.g. `'21 22'` for testing). Default is all autosomes `1 2 3 ... 22`. Chromosome names must NOT have a `chr` prefix.
- `--af-max` sets the maximum alternate allele frequency threshold (`AFMax`). Resolution order: (1) explicit `--af-max` always wins; (2) if omitted, the helper derives it from `--gnomad-version` — `0.0001` for `v2exome`, `0.0005` for `v4exome`/`v4genome`; (3) if both are omitted, `AFMax` is left out of the generated params and the pipeline's own default (`0.0005`) applies.
- Do not use `-c` for pipeline parameters; use `--params-file` or CLI flags.
- Do not invent nf-core parameters not in the schema.
- For run mode, verify runtime prerequisites: Java 17+, Nextflow, and profile-specific tools (docker, singularity/apptainer, conda/mamba).

## Troubleshooting

Ordered triage:

1. **Missing VCF index**: ensure `.tbi` or `.csi` index exists alongside `.vcf.gz`.
2. **Missing control data folder**: download from S3 before running.
3. **Reference/gnomAD version mismatch**: GRCh37 requires v2exome; GRCh38 requires v4exome or v4genome.
4. **Missing annotation resources**: download annovarFolder or vepFolder from S3.
5. **Submission failure**: inspect launcher stderr/stdout, verify queue/account/resources.
6. **Pipeline-level failure**: check `.nextflow.log`, then `pipeline_info/`, then failed task dirs under `work/`.
7. **Outputs missing**: check MultiQC report and primary output folders under outdir (cocorv/, annotation/, qc/).

## Agent Response Requirements

Every response should include:
- Exact command or generated script path used
- Confirmation that validation was performed
- Whether run type was dry-run or execution
- Scheduler job ID when available
- Clear next triage step

## References

- Helper script: `scripts/run_rarevariantburden.py`
- Agent playbook: `references/agent-playbook.md`
- Config and outputs: `references/config-and-output.md`
- Pipeline guide: `references/rarevariantburden_guide.md`
- Environment: `environment/nextflow-env.yml`
