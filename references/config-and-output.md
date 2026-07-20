# RareVariantBurden: Config and Output Reference

> **Development pipeline**: nf-core/rarevariantburden is not yet released. Always run from a local
> repository clone via `--repo-path`. Do NOT use `nextflow run nf-core/rarevariantburden`.

## Pipeline Parameters (nextflow_schema.json summary)

| Parameter | CLI flag | Type | Default | Description |
|---|---|---|---|---|
| `caseJointVCF` | `--caseJointVCF` | string | — | Joint-called VQSR VCF (.vcf.gz) |
| `caseSample` | `--caseSample` | string | — | Text file, one sample ID per line |
| `controlDataFolder` | `--controlDataFolder` | string | — | Local gnomAD control dataset folder |
| `outdir` | `--outdir` | string | — | Output directory |
| `reference` | `--reference` | string | — | `GRCh37` or `GRCh38` |
| `gnomADVersion` | `--gnomADVersion` | string | — | `v2exome`, `v4exome`, or `v4genome` |
| `annotationTool` | `--annotationTool` | string | `ANNOVAR` | `ANNOVAR`, `VEP`, or `ANNOVAR_VEP` (run both) |
| `annovarFolder` | `--annovarFolder` | string | — | ANNOVAR resource folder |
| `vepFolder` | `--vepFolder` | string | — | VEP resource folder |
| `genderFile` | `--genderFile` | string | — | Optional gender file for sex-stratified analysis |
| `topKGenes` | `--topKGenes` | integer | — | Number of top genes for detailed output |
| `AFMax` | `--AFMax` (helper: `--af-max`) | number | `0.0005` (pipeline); helper derives `0.0001`/`0.0005` from `--gnomad-version` when `--af-max` is omitted | Maximum alternate allele frequency threshold. See helper resolution order below. |
| `chrSet` | `--chrSet` | string | `1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22` | Space-separated chromosome list **without** `chr` prefix. Default is all autosomes 1–22. Example subset for testing: `'21 22'`. |
| `ACANConfig` | `--acan-config` | file path | `<controlDataFolder>/stratified_config_gnomadV4.asj.txt` | Ancestry group configuration file for CoCoRV stratified analysis. Override only if using a custom ancestry stratification. |
| `variantExclude` | `--variant-exclude` | file path | `<controlDataFolder>/gnomAD41WGSExtraExcludeInCodingExcludeTAS2R46.txt.gz` | One-column file of variants to exclude from analysis. Override only if using a custom exclusion list. |

## Skip-Ahead Parameters

All skip-ahead parameters default to `"NA"` in the pipeline; omit them or set to `"NA"` to use the standard path.
`caseGenotypeGDSFileList` and `caseAnnotationGDSFileList` must always be supplied together.

| Parameter | Helper flag | CSV columns | Skips |
|---|---|---|---|
| `caseVCFFileList` | `--case-vcf-file-list` | `chr,vcf` | `splitJointVCF`. Requires `caseJointVCF: NA`. |
| `caseNormalizedVCFFileList` | `--case-normalized-vcf-file-list` | `chr,vcf,index` | `normalizeQC`. Requires `caseVCFFileList`. |
| `caseAnnotatedVCFFileList` | `--case-annotated-vcf-file-list` | `chr,vcf,index` | ANNOVAR/VEP annotation entirely. |
| `caseGenotypeGDSFileList` | `--case-genotype-gds-file-list` | `chr,gds` | GDS genotype conversion. Paired with below. |
| `caseAnnotationGDSFileList` | `--case-annotation-gds-file-list` | `chr,gds` | GDS annotation conversion. Paired with above. |
| `casePopulation` | `--case-population` | (plain file path) | gnomAD position extraction + RF ancestry prediction. |

**Note**: The parameter for ANNOVAR is `annovarFolder`. Use `--annovarFolder` on the CLI or `annovarFolder:` in a params YAML file.

---

## Generated Artifacts (by helper script)

After running the helper, these files are created in `--outdir`:

| File | Description |
|---|---|
| `rarevariantburden.params.generated.yaml` | Generated Nextflow params YAML |
| `run_rarevariantburden.<executor>.sh` | Launch script with scheduler headers |

---

## Pipeline Output Structure

```
<outdir>/
├── cocorv/                    # CoCoRV association test results
│   ├── merged_results.tsv     # All-chromosome merged burden results
│   ├── fdr_results.tsv        # FDR-adjusted results
│   ├── qq_plot.pdf            # QQ plot
│   ├── lambda_values.tsv      # Inflation factor per analysis group
│   └── topK_genes/            # Top-K gene variant/sample lists
├── annotation/                # Per-chromosome annotated VCF/GDS files
│   ├── chr*/                  # Chromosome-split, normalized, annotated
│   └── gds/                   # GDS format files for R processing
├── ethnicity/                 # Ethnicity prediction outputs
│   ├── predicted_ancestry.tsv
│   └── ancestry_plot.pdf
├── qc/                        # QC metrics and BCFtools stats
├── pipeline_info/             # Nextflow pipeline execution reports
│   ├── execution_report.html
│   ├── execution_timeline.html
│   └── execution_trace.txt
├── multiqc/                   # MultiQC aggregated QC report
│   └── multiqc_report.html
└── work/                      # Nextflow work directory (intermediate files)
```

---

## Profile Options

| Profile | Container | Notes |
|---|---|---|
| `singularity` | Singularity/Apptainer | Recommended for HPC |
| `docker` | Docker | Requires Docker daemon |
| `conda` | Conda/Mamba | Slower startup |
| `test` | Any | Small test dataset run |

Combine with institute-specific config: `--profile singularity,sanger`

---

## Nextflow Configuration

Always run via a local repository clone:
```bash
nextflow run /path/to/rarevariantburden/main.nf ...
```
Do NOT use `nextflow run nf-core/rarevariantburden` — the pipeline is in development and has no stable release.

## Runtime Resolution

The helper resolves the nextflow runtime in this order:

1. `--use-current-path` → skip conda, use current PATH.
2. Conda env named by `--conda-env` found → use it.
3. `--create-conda-env` → create env from `environment/nextflow-env.yml`, then use.
4. Conda env not found → **fall back to PATH**: check `nextflow` + `java >= 17` on PATH.
   - Both found → log and proceed.
   - Missing → warn (dry-run) or fail with remediation message (run mode).

## Singularity Cache Directory

Set with `--singularity-cache <absolute-path>`. The helper exports `NXF_SINGULARITY_CACHEDIR`:
- Into the **current process** `os.environ` — inherited by locally launched Nextflow.
- Into the **generated launch script** — available to scheduler-submitted jobs.

```bash
--singularity-cache /research/rgs01/home/clusterHome/stithi/singularity-cache
# Generates in launch script:
export NXF_SINGULARITY_CACHEDIR=/research/rgs01/home/clusterHome/stithi/singularity-cache
```

Do NOT use `-c` to pass pipeline parameters. Use either:
1. `--params-file rarevariantburden.params.generated.yaml`
2. Direct CLI flags: `--caseJointVCF /path/to/file.vcf.gz ...`

Use `-c` only for Nextflow resource/executor config (not pipeline params).

---

## Key Output Files for Agent Triage

After a completed run, check these first:

1. `multiqc/multiqc_report.html` — Overall QC summary
2. `cocorv/fdr_results.tsv` — Final FDR-adjusted burden test results
3. `cocorv/qq_plot.pdf` — QQ plot for inflation assessment
4. `cocorv/topK_genes/` — Detailed variant lists for top candidate genes
5. `pipeline_info/execution_report.html` — Nextflow run summary

---

## Failure Checkpoints

| Stage | Where to look |
|---|---|
| Launch / submission | Helper stderr, scheduler output |
| Nextflow startup | `.nextflow.log` in outdir |
| Process crash | `pipeline_info/execution_trace.txt` → failed task hash → `work/<hash>/` |
| QC failure | `qc/` subdirectory |
| Annotation failure | `annotation/` subdirectory, check annovar/vep resource paths |
| CoCoRV failure | `cocorv/` subdirectory, R log files |

---

## AWS HealthOmics / DNAnexus

The pipeline supports cloud deployment on AWS HealthOmics and DNAnexus.
See `awshealthomics.md` and `dnanexus.md` in the pipeline repository for platform-specific instructions.
For AWS HealthOmics, the `aws-healthomics` MCP skill may be used to manage workflow runs.
