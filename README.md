# RareVariantBurden Skill

Agent-oriented skill assets for operating the **nf-core/rarevariantburden** pipeline (CoCoRV-nf) — a rare variant burden test pipeline for case-only genetic studies using gnomAD public summary counts as controls.

> You must clone the repository locally
> and always pass `--repo-path`. Do NOT use `nextflow run nf-core/rarevariantburden`.
>
> ```bash
> git clone https://github.com/nf-core/rarevariantburden.git
> ```

## Minimal Inputs

Required run inputs:

- Local repository clone path (`--repo-path`, must contain main.nf)
- Joint-called and VQSR-applied VCF path (`.vcf.gz` with tabix index) **or** pre-split VCF CSV (`--case-vcf-file-list`)
- Case samples text file (one sample ID per line)
- Control data folder (downloaded gnomAD summary counts)
- Output directory
- Reference genome build: `GRCh37` or `GRCh38`
- annotation tool folder (ANNOVAR or VEP or both)

### Skip-Ahead Inputs

If you have pre-computed intermediate files, you can skip earlier pipeline stages:

| Flag | CSV columns | Skips |
|---|---|---|
| `--case-vcf-file-list` | `chr,vcf` | joint VCF splitting. Set `--case-vcf NA`. |
| `--case-normalized-vcf-file-list` | `chr,vcf,index` | normalization/QC. Requires `--case-vcf-file-list`. |
| `--case-annotated-vcf-file-list` | `chr,vcf,index` | ANNOVAR/VEP annotation. |
| `--case-genotype-gds-file-list` | `chr,gds` | GDS genotype conversion. Pair with below. |
| `--case-annotation-gds-file-list` | `chr,gds` | GDS annotation conversion. Pair with above. |
| `--case-population` | (plain file path) | gnomAD ancestry prediction. |

## Control Data Download

```bash
# GRCh38 exome (most common)
aws s3 cp s3://cocorv-resource-files/gnomADv4.1exome/ /local/gnomADv4.1exome/ --recursive
aws s3 cp s3://cocorv-resource-files/annovarFolder/ /local/annovar/ --recursive

# GRCh37
aws s3 cp s3://cocorv-resource-files/gnomADv2exome/ /local/gnomADv2exome/ --recursive
```

## Quick Start

Dry-run validation:

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

Run mode (local):

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
  --executor local \
  --run
```

LSF submission:

```bash
python scripts/run_rarevariantburden.py \
 --repo-path /path/to/rarevariantburden \
 --case-vcf /path/to/joint.vcf.gz \
 --case-samples /path/to/samples.txt \
 --control-data-folder /path/to/gnomADv2exome \
 --outdir /path/to/output \
 --reference GRCh37 \
 --gnomad-version v2exome \
 --annovar-folder /path/to/annovarFolder \
 --profile singularity,stjude_lsf \
 --executor lsf \
 --queue priority \
 --project my_account \
 --cpus 8 \
 --memory-gb 8 \
 --walltime 16:00 \
 --run
```

Slurm submission:

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

## Repository Layout

- `SKILL.md`: Agent operating protocol and troubleshooting logic
- `scripts/run_rarevariantburden.py`: Helper entrypoint
- `environment/nextflow-env.yml`: Conda environment template
- `references/agent-playbook.md`: Concise operation playbook
- `references/config-and-output.md`: Config/output mapping
- `references/rarevariantburden_guide.md`: Extended usage notes

## Examples

### Example 1: Standard full run (joint VCF → results)

```bash
python scripts/run_rarevariantburden.py \
  --repo-path /path/to/nf-core-rarevariantburden \
  --case-vcf /data/joint.vcf.gz \
  --case-samples /data/samples.txt \
  --control-data-folder /data/gnomADv4.1exome \
  --outdir ./results \
  --reference GRCh38 \
  --gnomad-version v4exome \
  --annovar-folder /data/annovar \
  --profile singularity \
  --executor local --run
```

### Example 2: Start from pre-split per-chromosome VCFs

```bash
# CSV format for --case-vcf-file-list (header required):
# chr,vcf
# chr21,/data/split/chr21.vcf.gz
# chr22,/data/split/chr22.vcf.gz

python scripts/run_rarevariantburden.py \
  --repo-path /path/to/nf-core-rarevariantburden \
  --case-vcf NA \
  --case-vcf-file-list /data/split_vcfs.csv \
  --case-samples /data/samples.txt \
  --control-data-folder /data/gnomADv4.1exome \
  --outdir ./results \
  --reference GRCh38 --gnomad-version v4exome \
  --annovar-folder /data/annovar \
  --profile singularity --executor local --run
```

### Example 3: Start from pre-split + pre-normalized VCFs

```bash
# CSV format for --case-normalized-vcf-file-list:
# chr,vcf,index
# chr21,/data/norm/chr21.norm.vcf.gz,/data/norm/chr21.norm.vcf.gz.tbi
# chr22,/data/norm/chr22.norm.vcf.gz,/data/norm/chr22.norm.vcf.gz.tbi

python scripts/run_rarevariantburden.py \
  --repo-path /path/to/nf-core-rarevariantburden \
  --case-vcf NA \
  --case-vcf-file-list /data/split_vcfs.csv \
  --case-normalized-vcf-file-list /data/norm_vcfs.csv \
  --case-samples /data/samples.txt \
  --control-data-folder /data/gnomADv4.1exome \
  --outdir ./results \
  --reference GRCh38 --gnomad-version v4exome \
  --annovar-folder /data/annovar \
  --profile singularity --executor local --run
```

### Example 4: Start from pre-annotated VCFs (skip ANNOVAR/VEP)

```bash
# CSV format for --case-annotated-vcf-file-list:
# chr,vcf,index
# chr21,/data/annot/chr21.annot.vcf.gz,/data/annot/chr21.annot.vcf.gz.tbi
# chr22,/data/annot/chr22.annot.vcf.gz,/data/annot/chr22.annot.vcf.gz.tbi

python scripts/run_rarevariantburden.py \
  --repo-path /path/to/nf-core-rarevariantburden \
  --case-vcf NA \
  --case-vcf-file-list /data/split_vcfs.csv \
  --case-annotated-vcf-file-list /data/annot_vcfs.csv \
  --case-samples /data/samples.txt \
  --control-data-folder /data/gnomADv4.1exome \
  --outdir ./results \
  --reference GRCh38 --gnomad-version v4exome \
  --profile singularity --executor local --run
```

### Example 5: Start from pre-converted GDS files (skip VCF→GDS)

```bash
# CSV format for --case-genotype-gds-file-list and --case-annotation-gds-file-list:
# chr,gds
# chr21,/data/gds/chr21.geno.gds
# chr22,/data/gds/chr22.geno.gds

python scripts/run_rarevariantburden.py \
  --repo-path /path/to/nf-core-rarevariantburden \
  --case-vcf NA \
  --case-vcf-file-list /data/split_vcfs.csv \
  --case-annotated-vcf-file-list /data/annot_vcfs.csv \
  --case-genotype-gds-file-list /data/geno_gds.csv \
  --case-annotation-gds-file-list /data/annot_gds.csv \
  --case-samples /data/samples.txt \
  --control-data-folder /data/gnomADv4.1exome \
  --outdir ./results \
  --reference GRCh38 --gnomad-version v4exome \
  --profile singularity --executor local --run
```

### Example 6: Skip ancestry prediction (pre-computed population file)

```bash
python scripts/run_rarevariantburden.py \
  --repo-path /path/to/nf-core-rarevariantburden \
  --case-vcf NA \
  --case-vcf-file-list /data/split_vcfs.csv \
  --case-annotated-vcf-file-list /data/annot_vcfs.csv \
  --case-genotype-gds-file-list /data/geno_gds.csv \
  --case-annotation-gds-file-list /data/annot_gds.csv \
  --case-population /data/ancestry_prediction.tsv \
  --case-samples /data/samples.txt \
  --control-data-folder /data/gnomADv4.1exome \
  --outdir ./results \
  --reference GRCh38 --gnomad-version v4exome \
  --profile singularity --executor local --run
```

### Example 7: Slurm submission with singularity cache

```bash
python scripts/run_rarevariantburden.py \
  --repo-path /path/to/nf-core-rarevariantburden \
  --case-vcf /data/joint.vcf.gz \
  --case-samples /data/samples.txt \
  --control-data-folder /data/gnomADv4.1exome \
  --outdir ./results \
  --reference GRCh38 --gnomad-version v4exome \
  --annovar-folder /data/annovar \
  --singularity-cache /research/rgs01/home/clusterHome/stithi/singularity-cache \
  --profile singularity \
  --executor slurm --queue compute --project my_account \
  --cpus 16 --memory-gb 64 --walltime 48:00 \
  --run
```

## Notes

- Always dry-run first in new environments.
- Reference GRCh37 → use gnomAD version `v2exome`.
- Reference GRCh38 → use gnomAD version `v4exome` or `v4genome`.
- Default annotation tool is ANNOVAR (`annotationTool: ANNOVAR`). Valid values: ANNOVAR, VEP, ANNOVAR_VEP.
- Use `--chr-set '21 22'` to restrict to specific chromosomes (e.g. for testing). Default is `'1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22'`. No `chr` prefix — must match the pipeline schema exactly.
- `--acan-config` and `--variant-exclude` override the corresponding files that the pipeline resolves automatically from inside `--control-data-folder`. Only provide these if you need custom ancestry stratification or a custom variant exclusion list.
- Scheduler execution selected with `--executor` (`lsf`, `slurm`, `pbs`, `sge`).
- Full behavior contract, triage order, and response requirements are in `SKILL.md`.

## About

Based on the [nf-core/rarevariantburden](https://github.com/nf-core/rarevariantburden) pipeline implementing the CoCoRV method.
