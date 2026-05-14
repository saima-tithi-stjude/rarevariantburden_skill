## Development Status

nf-core/rarevariantburden is currently in active development with no stable release published.
**You must always clone the repository locally and pass the local path** — the `nextflow run nf-core/rarevariantburden` shorthand will not work.

```bash
git clone https://github.com/nf-core/rarevariantburden.git
```

---

# RareVariantBurden Extended Usage Guide

## Background

**nf-core/rarevariantburden** implements the **CoCoRV** (Consistent summary Count-based Rare Variant burden test) method, published in *Nature Communications* (PMID: 35545612). It is designed for case-only rare variant analysis where matched sequencing controls are unavailable; instead, pre-processed gnomAD summary counts serve as the reference population.

---

## Preparing Case Input Data

### 1. Joint-Called VCF

The pipeline requires a **joint-called and VQSR-applied VCF**. The recommended upstream pipeline is [nf-core/sarek](https://nf-co.re/sarek/) using the GATK joint germline variant calling module.

Requirements:
- File format: `.vcf.gz` (bgzip compressed)
- Must have a tabix index (`.tbi` or `.csi`)
- VQSR filtering applied
- Joint-called across all case samples

Index command:
```bash
tabix -p vcf joint_called.vcf.gz
```

### 2. Case Samples File

A plain text file with **one sample ID per line**, matching the IDs in the VCF header:

```
SAMPLE001
SAMPLE002
SAMPLE003
```

No spaces in sample IDs. No header line.

### 3. Gender File (Optional)

For sex-stratified analysis, provide a tab-delimited file:

```
SAMPLE001	F
SAMPLE002	M
SAMPLE003	F
```

Columns: sample_id, gender (M/F or Male/Female — check pipeline docs for exact format).

---

## Control Data

### Available Datasets

| Dataset | Build | S3 Path |
|---|---|---|
| gnomAD v2 exome | GRCh37 | `s3://cocorv-resource-files/gnomADv2exome/` |
| gnomAD v4.1 exome | GRCh38 | `s3://cocorv-resource-files/gnomADv4.1exome/` |
| gnomAD v4.1 genome | GRCh38 | `s3://cocorv-resource-files/gnomADv4.1genome/` |

### Listing Available Files

```bash
aws s3 ls s3://cocorv-resource-files/
```

### Download Strategy

Use `--recursive` for full dataset. These are large; consider downloading to shared storage:

```bash
aws s3 cp s3://cocorv-resource-files/gnomADv4.1exome/ /shared/gnomAD/v4.1exome/ \
  --recursive --no-progress
```

---

## Annotation Resources

### ANNOVAR (default)

```bash
aws s3 cp s3://cocorv-resource-files/annovarFolder/ /shared/annovar/ --recursive
```

Use: `--annovar-folder /shared/annovar`

### VEP (alternative)

```bash
aws s3 cp s3://cocorv-resource-files/vepFolder/ /shared/vep/ --recursive
```

Use: `--vep-folder /shared/vep --annotation-tool VEP`

---

## Ethnicity Stratification

The pipeline automatically predicts ancestry/ethnicity using a gnomAD-trained random forest classifier. Results are used to:
- Group cases into ancestry populations
- Match each group against the appropriate gnomAD population-specific summary counts
- Perform stratified burden tests to control for population stratification

This does not require any user action — it is part of the standard pipeline run.

---

## Multiple Testing Correction

The pipeline uses FDR (False Discovery Rate) control specifically designed for discrete count data. Standard FDR methods (Benjamini-Hochberg) are not always appropriate when alleles are very rare, as p-values under the null deviate from uniform. CoCoRV provides accurate inflation factor (lambda) estimates and generates QQ plots to assess calibration.

---

## Recessive Models

For recessive burden analysis, CoCoRV can exclude double heterozygous variants due to high linkage disequilibrium in populations. This is handled internally by the CoCoRV R package.

---

## Resume Capability

If a pipeline run is interrupted, use `--resume` to continue from the last checkpoint:

```bash
python scripts/run_rarevariantburden.py \
  ... [same arguments] \
  --resume \
  --run
```

Nextflow caches each completed task's outputs in the `work/` directory. Rerunning with `-resume` skips already-completed steps.

---

## Cloud Deployment

### AWS HealthOmics

See `awshealthomics.md` in the pipeline repository. Key steps:
1. Store inputs in S3
2. Use `aws-create-workflow.sh` to register the workflow
3. Submit runs via the AWS HealthOmics console or CLI
4. Use `aws.parameter.template.json` as the run parameter template

The `aws-healthomics` MCP skill can help automate these steps.

### DNAnexus

See `dnanexus.md` in the pipeline repository.

---

## Interpreter and R Dependency Notes

The CoCoRV association test runs in R using the `CoCoRV` package and `seqarray`. These are included in the pipeline containers (Docker/Singularity images). If running with `--profile conda`, ensure the conda environment includes these R packages.

---

## Common Parameter Mistakes

| Mistake | Correct approach |
|---|---|
| `nextflow run nf-core/rarevariantburden ...` | Use local clone: `nextflow run /path/to/rarevariantburden/main.nf ...` |
| `--reference hg19` | Use `--reference GRCh37` |
| `--reference hg38` | Use `--reference GRCh38` |
| `-c params.config` for parameters | Use `--params-file params.yaml` or CLI flags |
| `--annovarFolder` | Use `--annovar-folder` (helper) → `--annovarFolder` (pipeline) |
| Passing unindexed VCF | Always index with `tabix -p vcf <file.vcf.gz>` first |
| gnomAD v4 with GRCh37 | v4 only supports GRCh38 |

---

## Minimal Test Run

The pipeline supports `-profile test` for a quick sanity check with bundled test data.
Note: always run from the local repository clone — no published release exists yet:

```bash
# Clone the repo first (one-time)
git clone https://github.com/nf-core/rarevariantburden.git

# Test run using local clone
nextflow run rarevariantburden/main.nf -profile test,docker --outdir test_output
```

Run this in a new environment to verify containers and dependencies before using real data.
