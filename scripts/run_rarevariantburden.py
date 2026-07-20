"""Prepare, validate, and optionally launch nf-core/rarevariantburden across platforms."""

import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

SCHEDULER_CMDS = {
    "lsf": "bsub",
    "slurm": "sbatch",
    "pbs": "qsub",
    "sge": "qsub",
}

# gnomAD version <-> reference compatibility
GNOMAD_REFERENCE_MAP = {
    "v2exome": ["GRCh37"],
    "v4exome": ["GRCh38"],
    "v4genome": ["GRCh38"],
}

# Recommended AFMax (max alternate allele frequency) per gnomAD control version.
# Used only when the user does not explicitly pass --af-max.
AFMAX_DEFAULTS_BY_GNOMAD_VERSION = {
    "v2exome": 0.0001,
    "v4exome": 0.0005,
    "v4genome": 0.0005,
}

VALID_REFERENCES = ["GRCh37", "GRCh38"]
VALID_GNOMAD_VERSIONS = list(GNOMAD_REFERENCE_MAP.keys())
VALID_ANNOTATION_TOOLS = ["ANNOVAR", "VEP", "ANNOVAR_VEP"]

MIN_JAVA_MAJOR = 17


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fail(message):
    print(f"[ERROR] {message}", file=sys.stderr)
    raise SystemExit(1)


def info(message):
    print(f"[INFO] {message}")


def warn(message):
    print(f"[WARN] {message}")


def script_dir():
    return Path(__file__).resolve().parent


def is_remote_path(path):
    if not path:
        return False
    parsed = urlparse(path)
    return parsed.scheme in {"http", "https", "s3", "gs", "ftp"}


def normalize_walltime_hhmmss(value, label):
    if re.fullmatch(r"\d{1,3}:\d{2}:\d{2}", value):
        return value
    if re.fullmatch(r"\d{1,3}:\d{2}", value):
        return f"{value}:00"
    fail(f"Invalid {label} format: {value!r}. Use HH:MM or HH:MM:SS")


def resolve_af_max(args):
    """Resolve the effective AFMax value.

    Precedence:
      1. User-specified --af-max: always used as-is.
      2. Not specified: derive from --gnomad-version
         (0.0001 for v2exome, 0.0005 for v4exome/v4genome).
      3. Neither specified: leave unset so the pipeline's own default (0.0005) applies.
    """
    if args.af_max is not None:
        return args.af_max
    if args.gnomad_version and args.gnomad_version in AFMAX_DEFAULTS_BY_GNOMAD_VERSION:
        derived = AFMAX_DEFAULTS_BY_GNOMAD_VERSION[args.gnomad_version]
        info(
            f"--af-max not specified; using {derived} as the recommended AFMax "
            f"for --gnomad-version {args.gnomad_version}."
        )
        return derived
    return None


def has_any_command(names):
    return next((name for name in names if shutil.which(name) is not None), "")


def detect_java_major_version():
    if shutil.which("java") is None:
        return None
    completed = subprocess.run(["java", "-version"], capture_output=True, text=True)
    raw = f"{completed.stdout}\n{completed.stderr}"
    match = re.search(r'version\s+"([0-9]+)(?:\.[0-9._]+)?"', raw)
    if match:
        return int(match.group(1))
    return None


def default_conda_env_file():
    return script_dir().parent / "environment" / "nextflow-env.yml"


def parse_env_list_output(raw_output, env_name):
    for line in raw_output.splitlines():
        line = line.strip()
        if not line or line.startswith("Name") or line.startswith("#"):
            continue
        tokens = line.split()
        path_token = next(
            (token for token in reversed(tokens) if token.startswith("/")), None
        )
        if path_token is None:
            continue
        prefix = Path(path_token)
        if prefix.name == env_name:
            return prefix
        if tokens and tokens[0] == env_name:
            return prefix
    return None


def find_conda_env_prefix(env_name):
    commands = []
    if shutil.which("mamba"):
        commands.append(["mamba", "env", "list"])
    if shutil.which("conda"):
        commands.append(["conda", "env", "list"])
    for cmd in commands:
        completed = subprocess.run(cmd, capture_output=True, text=True)
        combined = f"{completed.stdout}\n{completed.stderr}"
        prefix = parse_env_list_output(combined, env_name)
        if prefix is not None and prefix.exists():
            return prefix
    return None


def create_conda_env(env_name, env_file):
    env_file = Path(env_file).expanduser().resolve()
    if not env_file.exists():
        fail(f"Conda environment file does not exist: {env_file}")
    if shutil.which("mamba"):
        cmd = ["mamba", "env", "create", "-n", env_name, "-f", str(env_file)]
    elif shutil.which("conda"):
        cmd = ["conda", "env", "create", "-n", env_name, "-f", str(env_file)]
    else:
        fail("Neither mamba nor conda is available to create environment")
    info("Creating conda environment: " + " ".join(cmd))
    completed = subprocess.run(cmd)
    if completed.returncode != 0:
        fail(f"Environment creation failed with code {completed.returncode}")


def _check_path_runtime(args):
    """Return True if nextflow and java >= MIN_JAVA_MAJOR are available on PATH."""
    nf_on_path = shutil.which(args.nextflow_bin)
    if not nf_on_path:
        return False
    java_major = detect_java_major_version()
    if java_major is None or java_major < MIN_JAVA_MAJOR:
        return False
    return True


def resolve_runtime(args):
    """Resolve the Nextflow runtime, returning conda prefix path or None.

    Resolution order:
      1. --use-current-path: skip all conda logic, trust current PATH.
      2. Conda env found: use it, update args.nextflow_bin if nextflow is inside.
      3. --create-conda-env: create env, then retry step 2.
      4. Conda env still not found: fall back to checking PATH for nextflow + java >= 17.
         - If PATH has both: log and continue (args.nextflow_bin unchanged).
         - If PATH is missing either: warn (dry-run) or fail (run mode).
    """
    if args.use_current_path:
        info("--use-current-path set: skipping conda lookup, using current PATH.")
        return None

    prefix = find_conda_env_prefix(args.conda_env)

    if prefix is None and args.create_conda_env:
        env_file = args.conda_env_file or str(default_conda_env_file())
        create_conda_env(args.conda_env, env_file)
        prefix = find_conda_env_prefix(args.conda_env)

    if prefix is not None:
        nextflow_bin = prefix / "bin" / "nextflow"
        if nextflow_bin.exists():
            args.nextflow_bin = str(nextflow_bin)
            info(f"Using Nextflow from conda environment: {nextflow_bin}")
        else:
            warn(
                f"Conda environment found at {prefix}, but nextflow not found in {prefix / 'bin'}. "
                "Falling back to PATH lookup for nextflow."
            )
        return prefix

    # Conda env not found — fall through to PATH
    warn(f"Conda environment '{args.conda_env}' was not found. Checking PATH for nextflow and java.")
    if _check_path_runtime(args):
        java_major = detect_java_major_version()
        nf_path = shutil.which(args.nextflow_bin)
        info(
            f"Runtime resolved from PATH: nextflow={nf_path}, "
            f"java={shutil.which('java')} (version {java_major})."
        )
        return None

    # Neither conda nor PATH provides a usable runtime
    msg = (
        f"Could not resolve a usable runtime: conda environment '{args.conda_env}' not found "
        f"and nextflow/java (>= {MIN_JAVA_MAJOR}) not available on PATH.\n"
        "Options:\n"
        "  1. Re-run with --create-conda-env to create the conda environment.\n"
        "  2. Re-run with --use-current-path after loading nextflow and java modules.\n"
        "  3. Re-run with --module-load to inject a module load command into the launch script."
    )
    if args.run:
        fail(msg)
    warn(msg + "\nDry-run/generate-only continues.")
    return None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_repo_path(repo_path_str):
    """Validate the local pipeline repository path exists and contains main.nf."""
    repo = Path(repo_path_str).expanduser().resolve()
    if not repo.exists() or not repo.is_dir():
        fail(
            f"Repository path does not exist or is not a directory: {repo}\n"
            "Clone the pipeline first: git clone https://github.com/nf-core/rarevariantburden.git"
        )
    main_nf = repo / "main.nf"
    if not main_nf.exists():
        fail(
            f"Could not find main.nf in repository path: {repo}\n"
            "Ensure --repo-path points to the root of the cloned repository."
        )
    return str(repo)


def validate_inputs(args):
    # Repo path (always required — pipeline is in development, no nf-core shorthand)
    args.repo_path = validate_repo_path(args.repo_path)

    # Reference
    if args.reference not in VALID_REFERENCES:
        fail(f"--reference must be one of: {', '.join(VALID_REFERENCES)}. Got: {args.reference!r}")

    # gnomAD version compatibility
    if args.gnomad_version:
        if args.gnomad_version not in VALID_GNOMAD_VERSIONS:
            fail(
                f"--gnomad-version must be one of: {', '.join(VALID_GNOMAD_VERSIONS)}. "
                f"Got: {args.gnomad_version!r}"
            )
        allowed_refs = GNOMAD_REFERENCE_MAP[args.gnomad_version]
        if args.reference not in allowed_refs:
            fail(
                f"--gnomad-version {args.gnomad_version!r} is only compatible with "
                f"--reference {'/'.join(allowed_refs)}, but got --reference {args.reference!r}"
            )

    # Annotation tool
    if args.annotation_tool not in VALID_ANNOTATION_TOOLS:
        fail(
            f"--annotation-tool must be one of: {', '.join(VALID_ANNOTATION_TOOLS)}. "
            f"Got: {args.annotation_tool!r}"
        )

    # ---- Case VCF / skip-ahead mutual exclusion rules ----
    using_vcf_file_list = bool(args.case_vcf_file_list)

    if using_vcf_file_list:
        # User is providing pre-split VCFs — caseJointVCF must be "NA"
        if args.case_vcf != "NA":
            fail(
                "--case-vcf-file-list was provided but --case-vcf is not 'NA'. "
                "When using --case-vcf-file-list, set --case-vcf NA (or omit it; 'NA' is the default)."
            )
        _check_csv_file(args.case_vcf_file_list, ["chr", "vcf"], "--case-vcf-file-list")
    else:
        # Standard path: joint VCF is required
        if args.case_vcf == "NA":
            fail(
                "--case-vcf is 'NA' but --case-vcf-file-list was not provided. "
                "Either supply a joint VCF with --case-vcf or provide split VCFs with --case-vcf-file-list."
            )
        if not is_remote_path(args.case_vcf):
            if not os.path.exists(args.case_vcf):
                fail(f"Case VCF does not exist: {args.case_vcf}")
            _check_vcf_index(args.case_vcf)

    # caseNormalizedVCFFileList only valid when caseVCFFileList is also set
    if args.case_normalized_vcf_file_list and not using_vcf_file_list:
        fail(
            "--case-normalized-vcf-file-list requires --case-vcf-file-list to also be provided "
            "(the pipeline only accepts pre-normalized VCFs when the input is already split)."
        )
    if args.case_normalized_vcf_file_list:
        _check_csv_file(args.case_normalized_vcf_file_list, ["chr", "vcf", "index"],
                        "--case-normalized-vcf-file-list")

    # caseAnnotatedVCFFileList
    if args.case_annotated_vcf_file_list:
        _check_csv_file(args.case_annotated_vcf_file_list, ["chr", "vcf", "index"],
                        "--case-annotated-vcf-file-list")

    # caseGenotypeGDSFileList and caseAnnotationGDSFileList must be paired
    if bool(args.case_genotype_gds_file_list) != bool(args.case_annotation_gds_file_list):
        fail(
            "--case-genotype-gds-file-list and --case-annotation-gds-file-list must be "
            "provided together (both or neither)."
        )
    if args.case_genotype_gds_file_list:
        _check_csv_file(args.case_genotype_gds_file_list, ["chr", "gds"],
                        "--case-genotype-gds-file-list")
        _check_csv_file(args.case_annotation_gds_file_list, ["chr", "gds"],
                        "--case-annotation-gds-file-list")

    # casePopulation
    if args.case_population:
        if not is_remote_path(args.case_population) and not os.path.exists(args.case_population):
            fail(f"Case population file does not exist: {args.case_population}")

    # ---- Standard required file checks ----
    if not is_remote_path(args.case_samples):
        if not os.path.exists(args.case_samples):
            fail(f"Case samples file does not exist: {args.case_samples}")
        _check_samples_file(args.case_samples)

    if not is_remote_path(args.control_data_folder):
        if not os.path.exists(args.control_data_folder):
            fail(
                f"Control data folder does not exist: {args.control_data_folder}\n"
                "Download from S3: aws s3 cp s3://cocorv-resource-files/<version>/ <local-dir>/ --recursive"
            )
        if not os.path.isdir(args.control_data_folder):
            fail(f"--control-data-folder must be a directory: {args.control_data_folder}")

    # ---- Annotation folders ----
    # Skip annotation folder warnings if caseAnnotatedVCFFileList is supplied
    # (annotation step will be bypassed entirely)
    annotation_skipped = bool(args.case_annotated_vcf_file_list)
    if not annotation_skipped:
        if args.annotation_tool in ("ANNOVAR", "ANNOVAR_VEP") and args.annovar_folder:
            if not is_remote_path(args.annovar_folder) and not os.path.exists(args.annovar_folder):
                fail(f"ANNOVAR folder does not exist: {args.annovar_folder}")
        if args.annotation_tool in ("VEP", "ANNOVAR_VEP") and args.vep_folder:
            if not is_remote_path(args.vep_folder) and not os.path.exists(args.vep_folder):
                fail(f"VEP folder does not exist: {args.vep_folder}")
        if args.annotation_tool in ("ANNOVAR", "ANNOVAR_VEP") and not args.annovar_folder:
            warn(
                "--annotation-tool includes ANNOVAR but --annovar-folder was not provided. "
                "The pipeline will fail at the annotation step unless annovarFolder is supplied."
            )
        if args.annotation_tool in ("VEP", "ANNOVAR_VEP") and not args.vep_folder:
            warn(
                "--annotation-tool includes VEP but --vep-folder was not provided. "
                "The pipeline will fail at the annotation step unless vepFolder is supplied."
            )

    # ACANConfig (optional override)
    if args.acan_config and not is_remote_path(args.acan_config):
        if not os.path.exists(args.acan_config):
            fail(f"ACANConfig file does not exist: {args.acan_config}")

    # variantExclude (optional override)
    if args.variant_exclude and not is_remote_path(args.variant_exclude):
        if not os.path.exists(args.variant_exclude):
            fail(f"variantExclude file does not exist: {args.variant_exclude}")

    # gender file (optional)
    if args.gender_file and not is_remote_path(args.gender_file):
        if not os.path.exists(args.gender_file):
            fail(f"Gender file does not exist: {args.gender_file}")


def _check_vcf_index(vcf_path):
    """Warn if no .tbi or .csi index is found for the VCF."""
    tbi = vcf_path + ".tbi"
    csi = vcf_path + ".csi"
    if not os.path.exists(tbi) and not os.path.exists(csi):
        warn(
            f"No .tbi or .csi index found alongside VCF: {vcf_path}\n"
            "Index with: tabix -p vcf <vcf.gz>"
        )


def _check_csv_file(path, required_columns, flag_name):
    """Validate a CSV skip-ahead file exists and has the expected header columns."""
    if is_remote_path(path):
        return  # can't inspect remote files
    if not os.path.exists(path):
        fail(f"{flag_name}: CSV file does not exist: {path}")
    with open(path, "r") as fh:
        header_line = fh.readline().strip()
    if not header_line:
        fail(f"{flag_name}: CSV file is empty: {path}")
    actual_cols = [c.strip() for c in header_line.split(",")]
    missing = [c for c in required_columns if c not in actual_cols]
    if missing:
        fail(
            f"{flag_name}: CSV file is missing required column(s): {missing}\n"
            f"  Expected columns: {required_columns}\n"
            f"  Found columns:    {actual_cols}\n"
            f"  File: {path}"
        )


def _check_samples_file(samples_path):
    """Check the samples file is non-empty and contains valid-looking IDs."""
    with open(samples_path, "r") as fh:
        lines = [line.strip() for line in fh if line.strip()]
    if not lines:
        fail(f"Case samples file is empty: {samples_path}")
    for line in lines:
        if any(ch.isspace() for ch in line):
            fail(f"Sample ID contains whitespace in {samples_path}: {line!r}")
    info(f"Case samples file validated: {len(lines)} sample(s) found.")


def ensure_runtime_tools(args):
    nextflow_missing = shutil.which(args.nextflow_bin) is None
    if args.run and nextflow_missing:
        fail(f"Could not find Nextflow executable: {args.nextflow_bin}")
    if not args.run and nextflow_missing:
        warn(
            f"Nextflow executable not found ({args.nextflow_bin}). "
            "Dry-run/generate-only modes can continue without Nextflow."
        )
    if args.run and args.executor in SCHEDULER_CMDS:
        submit_cmd = SCHEDULER_CMDS[args.executor]
        if shutil.which(submit_cmd) is None:
            fail(f"{submit_cmd} is required for --run with --executor {args.executor}")


def ensure_dependency_tools(args):
    profile_items = [item.strip().lower() for item in args.profile.split(",") if item.strip()]
    missing_run = []
    missing_warn = []

    java_cmd = has_any_command(["java"])
    java_major = detect_java_major_version()

    if not java_cmd:
        (missing_run if args.run else missing_warn).append("java")
    elif java_major is None:
        warn("Unable to detect Java version. Nextflow requires Java 17 or later.")
    elif java_major < MIN_JAVA_MAJOR:
        (missing_run if args.run else missing_warn).append(f"java>={MIN_JAVA_MAJOR}")

    if "docker" in profile_items and not has_any_command(["docker"]):
        (missing_run if args.run else missing_warn).append("docker")

    if "singularity" in profile_items or "apptainer" in profile_items:
        if not has_any_command(["singularity", "apptainer"]):
            (missing_run if args.run else missing_warn).append("singularity|apptainer")

    if "conda" in profile_items and not has_any_command(["conda", "mamba"]):
        (missing_run if args.run else missing_warn).append("conda|mamba")

    if missing_warn:
        warn(
            "Potentially missing dependency tools for selected profile/runtime: "
            + ", ".join(sorted(set(missing_warn)))
            + ". Dry-run/generate-only continues."
        )
    if missing_run:
        fail(
            "Missing dependency tools for selected profile/runtime: "
            + ", ".join(sorted(set(missing_run)))
        )


# ---------------------------------------------------------------------------
# Artifact generation
# ---------------------------------------------------------------------------

def build_params_content(args):
    """Build the YAML params content for -params-file."""
    # caseJointVCF is always emitted; when using caseVCFFileList it must be "NA"
    lines = [
        f"caseJointVCF: {args.case_vcf}",
        f"caseSample: {args.case_samples}",
        f"controlDataFolder: {args.control_data_folder}",
        f"outdir: {args.outdir}",
        f"reference: {args.reference}",
    ]
    # Skip-ahead parameters — only emit when provided; pipeline defaults are "NA"
    if args.case_vcf_file_list:
        lines.append(f"caseVCFFileList: {args.case_vcf_file_list}")
    if args.case_normalized_vcf_file_list:
        lines.append(f"caseNormalizedVCFFileList: {args.case_normalized_vcf_file_list}")
    if args.case_annotated_vcf_file_list:
        lines.append(f"caseAnnotatedVCFFileList: {args.case_annotated_vcf_file_list}")
    if args.case_genotype_gds_file_list:
        lines.append(f"caseGenotypeGDSFileList: {args.case_genotype_gds_file_list}")
    if args.case_annotation_gds_file_list:
        lines.append(f"caseAnnotationGDSFileList: {args.case_annotation_gds_file_list}")
    if args.case_population:
        lines.append(f"casePopulation: {args.case_population}")
    # Standard optional params
    if args.gnomad_version:
        lines.append(f"gnomADVersion: {args.gnomad_version}")
    if args.annotation_tool:
        lines.append(f"annotationTool: {args.annotation_tool}")
    if args.annovar_folder:
        lines.append(f"annovarFolder: {args.annovar_folder}")
    if args.vep_folder:
        lines.append(f"vepFolder: {args.vep_folder}")
    if args.gender_file:
        lines.append(f"genderFile: {args.gender_file}")
    if args.top_k_genes:
        lines.append(f"topKGenes: {args.top_k_genes}")
    if args.af_max is not None:
        lines.append(f"AFMax: {args.af_max}")
    if args.acan_config:
        lines.append(f"ACANConfig: {args.acan_config}")
    if args.variant_exclude:
        lines.append(f"variantExclude: {args.variant_exclude}")
    if args.chr_set:
        lines.append(f"chrSet: {args.chr_set}")
    return "\n".join(lines) + "\n"


def write_params_file(args):
    params_path = os.path.join(args.outdir, args.params_config_name)
    os.makedirs(os.path.dirname(params_path) or ".", exist_ok=True)
    with open(params_path, "w", encoding="utf-8") as fh:
        fh.write(build_params_content(args))
    return params_path


def build_nextflow_command(args, generated_params_path):
    cmd = [
        args.nextflow_bin,
        "run",
        args.repo_path,
        "-profile",
        args.profile,
    ]
    if args.use_generated_params_file:
        cmd.extend(["-params-file", generated_params_path])
    else:
        # Pass parameters directly on CLI
        cmd.extend([
            "--caseJointVCF", args.case_vcf,
            "--caseSample", args.case_samples,
            "--controlDataFolder", args.control_data_folder,
            "--outdir", args.outdir,
            "--reference", args.reference,
        ])
        if args.gnomad_version:
            cmd.extend(["--gnomADVersion", args.gnomad_version])
        if args.annotation_tool:
            cmd.extend(["--annotationTool", args.annotation_tool])
        if args.annovar_folder:
            cmd.extend(["--annovarFolder", args.annovar_folder])
        if args.vep_folder:
            cmd.extend(["--vepFolder", args.vep_folder])
        if args.case_vcf_file_list:
            cmd.extend(["--caseVCFFileList", args.case_vcf_file_list])
        if args.case_normalized_vcf_file_list:
            cmd.extend(["--caseNormalizedVCFFileList", args.case_normalized_vcf_file_list])
        if args.case_annotated_vcf_file_list:
            cmd.extend(["--caseAnnotatedVCFFileList", args.case_annotated_vcf_file_list])
        if args.case_genotype_gds_file_list:
            cmd.extend(["--caseGenotypeGDSFileList", args.case_genotype_gds_file_list])
        if args.case_annotation_gds_file_list:
            cmd.extend(["--caseAnnotationGDSFileList", args.case_annotation_gds_file_list])
        if args.case_population:
            cmd.extend(["--casePopulation", args.case_population])
        if args.gender_file:
            cmd.extend(["--genderFile", args.gender_file])
        if args.top_k_genes:
            cmd.extend(["--topKGenes", str(args.top_k_genes)])
        if args.af_max is not None:
            cmd.extend(["--AFMax", str(args.af_max)])
        if args.acan_config:
            cmd.extend(["--ACANConfig", args.acan_config])
        if args.variant_exclude:
            cmd.extend(["--variantExclude", args.variant_exclude])
        if args.chr_set:
            cmd.extend(["--chrSet", args.chr_set])

    if args.resume:
        cmd.append("-resume")
    if args.with_report:
        cmd.extend(["-with-report", args.with_report])
    if args.with_dag:
        cmd.extend(["-with-dag", args.with_dag])
    if args.extra_args:
        cmd.extend(shlex.split(args.extra_args))
    return cmd


def scheduler_header_lines(args):
    mem_mb = int(args.memory_gb * 1024)
    stdout_path = os.path.join(args.logdir, args.stdout_file) if args.logdir else args.stdout_file
    stderr_path = os.path.join(args.logdir, args.stderr_file) if args.logdir else args.stderr_file
    walltime_hhmmss = normalize_walltime_hhmmss(args.walltime, "walltime")

    if args.executor == "lsf":
        lines = [
            f"#BSUB -J {args.job_name}",
            f"#BSUB -n {args.cpus}",
            f"#BSUB -M {mem_mb}",
            f"#BSUB -W {args.walltime}",
            f"#BSUB -o {stdout_path}",
            f"#BSUB -e {stderr_path}",
        ]
        if args.queue:
            lines.insert(1, f"#BSUB -q {args.queue}")
        if args.project:
            lines.insert(1, f"#BSUB -P {args.project}")
        return lines

    if args.executor == "slurm":
        lines = [
            f"#SBATCH --job-name={args.job_name}",
            f"#SBATCH --cpus-per-task={args.cpus}",
            f"#SBATCH --mem={mem_mb}",
            f"#SBATCH --time={args.walltime}",
            f"#SBATCH --output={stdout_path}",
            f"#SBATCH --error={stderr_path}",
        ]
        if args.queue:
            lines.insert(1, f"#SBATCH --partition={args.queue}")
        if args.project:
            lines.insert(1, f"#SBATCH --account={args.project}")
        return lines

    if args.executor == "pbs":
        lines = [
            f"#PBS -N {args.job_name}",
            f"#PBS -l select=1:ncpus={args.cpus}:mem={int(args.memory_gb)}gb",
            f"#PBS -l walltime={walltime_hhmmss}",
            f"#PBS -o {stdout_path}",
            f"#PBS -e {stderr_path}",
        ]
        if args.queue:
            lines.insert(1, f"#PBS -q {args.queue}")
        if args.project:
            lines.insert(1, f"#PBS -A {args.project}")
        return lines

    if args.executor == "sge":
        lines = [
            f"#$ -N {args.job_name}",
            f"#$ -pe smp {args.cpus}",
            f"#$ -l h_vmem={max(1, int(args.memory_gb / max(1, args.cpus)))}G",
            f"#$ -l h_rt={walltime_hhmmss}",
            f"#$ -o {stdout_path}",
            f"#$ -e {stderr_path}",
        ]
        if args.queue:
            lines.insert(1, f"#$ -q {args.queue}")
        if args.project:
            lines.insert(1, f"#$ -P {args.project}")
        return lines

    return []


def default_script_path(args):
    suffix = args.executor if args.executor in SCHEDULER_CMDS else "local"
    return os.path.join(args.outdir, f"run_rarevariantburden.{suffix}.sh")


def write_launch_script(args, script_path, nextflow_cmd):
    quoted_cmd = " ".join(shlex.quote(token) for token in nextflow_cmd)
    mkdir_targets = [args.outdir, args.workdir]
    if args.logdir:
        mkdir_targets.append(args.logdir)

    lines = ["#!/usr/bin/env bash"]
    lines.extend(scheduler_header_lines(args))
    lines.extend([
        "",
        "set -euo pipefail",
        f"mkdir -p {' '.join(shlex.quote(path) for path in mkdir_targets)}",
        f"export NXF_WORK={shlex.quote(args.workdir)}",
    ])
    if args.nxf_opts:
        lines.append(f"export NXF_OPTS={shlex.quote(args.nxf_opts)}")
    if args.singularity_cache:
        lines.append(f"export NXF_SINGULARITY_CACHEDIR={shlex.quote(args.singularity_cache)}")
    if args.runtime_prefix:
        lines.append(f"export PATH={shlex.quote(str(Path(args.runtime_prefix) / 'bin'))}:$PATH")
        lines.append(f"export CONDA_PREFIX={shlex.quote(str(args.runtime_prefix))}")
    lines.append("")
    if args.module_load:
        lines.append(args.module_load)
    lines.append(quoted_cmd)

    with open(script_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    os.chmod(script_path, 0o755)


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def submit_command_for_executor(executor, script_path):
    # Always resolve to absolute path so the command works from any cwd.
    abs_path = os.path.abspath(script_path)
    quoted = shlex.quote(abs_path)
    if executor == "lsf":
        return f"bsub < {quoted}"
    if executor == "slurm":
        return f"sbatch {quoted}"
    if executor in {"pbs", "sge"}:
        return f"qsub {quoted}"
    return f"bash {quoted}"


def extract_job_id(executor, output):
    patterns = {
        "lsf": r"<([0-9]+)>",
        "slurm": r"Submitted batch job\s+([0-9]+)",
        "pbs": r"^([0-9]+(?:\.[A-Za-z0-9_.-]+)?)$",
        "sge": r"job\s+([0-9]+)",
    }
    pattern = patterns.get(executor)
    if not pattern:
        return None
    for line in output.splitlines():
        match = re.search(pattern, line.strip())
        if match:
            return match.group(1)
    return None


def execute_launch(args, script_path):
    cmd = submit_command_for_executor(args.executor, script_path)
    is_local = args.executor not in SCHEDULER_CMDS

    if is_local:
        # Stream Nextflow output directly to the terminal so the user sees
        # live progress. Do not capture — Nextflow is long-running and its
        # stdout/stderr must not be buffered until exit.
        info(f"Launching locally: {cmd}")
        info("Nextflow output will stream below. Press Ctrl-C to interrupt.")
        print("", flush=True)
        completed = subprocess.run(cmd, shell=True)
        if completed.returncode != 0:
            fail(
                f"Pipeline exited with code {completed.returncode}. "
                "Check Nextflow output above and .nextflow.log for details."
            )
        print("")
        info("Pipeline completed successfully.")
    else:
        # Scheduler submission: short-lived command, capture output to
        # extract the job ID from the response line.
        completed = subprocess.run(cmd, shell=True, text=True, capture_output=True)
        stdout = (completed.stdout or "").strip()
        stderr = (completed.stderr or "").strip()
        if completed.returncode != 0:
            if stderr:
                print(stderr, file=sys.stderr)
            if stdout:
                print(stdout)
            fail(f"Scheduler submission failed with exit code {completed.returncode}")
        print("--- Submitted ---")
        if stdout:
            print(stdout)
        if stderr:
            print(stderr)
        job_id = extract_job_id(args.executor, stdout + "\n" + stderr)
        if job_id:
            info(f"Job ID: {job_id}")
        else:
            info("Submission succeeded. Check your scheduler queue for status.")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Prepare and optionally launch nf-core/rarevariantburden "
            "(CoCoRV-nf) for rare variant burden testing."
        )
    )

    # --- Required pipeline inputs ---
    req = parser.add_argument_group("Required pipeline inputs")
    req.add_argument("--case-vcf", default="NA",
                     help="Joint-called and VQSR-applied VCF file (.vcf.gz). "
                          "Set to 'NA' (the default) when providing --case-vcf-file-list instead.")
    req.add_argument("--case-samples", required=True,
                     help="Text file with one sample ID per line")
    req.add_argument("--control-data-folder", required=True,
                     help="Local path to downloaded gnomAD control dataset folder")
    req.add_argument("--outdir", required=True,
                     help="Output directory")
    req.add_argument("--reference", required=True, choices=VALID_REFERENCES,
                     help="Reference genome build: GRCh37 or GRCh38")

    # --- Skip-ahead inputs (pre-computed intermediate files) ---
    skip = parser.add_argument_group(
        "Skip-ahead inputs (pre-computed intermediates)",
        "Supply these to skip earlier pipeline stages. Each is a CSV file with a header row. "
        "When --case-vcf-file-list is provided, set --case-vcf to 'NA'."
    )
    skip.add_argument("--case-vcf-file-list", default="",
                      help="CSV file (columns: chr,vcf) of per-chromosome split VCF files. "
                           "Skips splitJointVCF. Requires --case-vcf NA.")
    skip.add_argument("--case-normalized-vcf-file-list", default="",
                      help="CSV file (columns: chr,vcf,index) of per-chromosome normalized VCF files. "
                           "Skips normalizeQC. Only valid when --case-vcf-file-list is also provided.")
    skip.add_argument("--case-annotated-vcf-file-list", default="",
                      help="CSV file (columns: chr,vcf,index) of per-chromosome annotated VCF files. "
                           "Skips ANNOVAR/VEP annotation entirely.")
    skip.add_argument("--case-genotype-gds-file-list", default="",
                      help="CSV file (columns: chr,gds) of per-chromosome case genotype GDS files. "
                           "Must be provided together with --case-annotation-gds-file-list. "
                           "Skips caseGenotypeGDS and caseAnnotationGDS conversion.")
    skip.add_argument("--case-annotation-gds-file-list", default="",
                      help="CSV file (columns: chr,gds) of per-chromosome case annotation GDS files. "
                           "Must be provided together with --case-genotype-gds-file-list.")
    skip.add_argument("--case-population", default="",
                      help="Path to a pre-computed population/ancestry prediction file for case samples. "
                           "Skips gnomAD position extraction, merging, and RF prediction entirely.")

    # --- Optional pipeline parameters ---
    opt = parser.add_argument_group("Optional pipeline parameters")
    opt.add_argument("--gnomad-version", default="",
                     choices=VALID_GNOMAD_VERSIONS + [""],
                     help="gnomAD version: v2exome (GRCh37), v4exome or v4genome (GRCh38)")
    opt.add_argument("--annotation-tool", default="ANNOVAR",
                     choices=VALID_ANNOTATION_TOOLS,
                     help="Annotation tool: ANNOVAR (default), VEP, or ANNOVAR_VEP (run both). "
                          "Values are case-sensitive and must be uppercase.")
    opt.add_argument("--annovar-folder", default="",
                     help="Path to ANNOVAR resource folder")
    opt.add_argument("--vep-folder", default="",
                     help="Path to VEP resource folder")
    opt.add_argument("--gender-file", default="",
                     help="Optional file with sample gender info for sex-stratified analysis")
    opt.add_argument("--top-k-genes", type=int, default=0,
                     help="Number of top genes for which to generate detailed variant/sample lists")
    opt.add_argument("--af-max", type=float, default=None,
                     help="Maximum alternate allele frequency threshold (AFMax). "
                          "If not specified, derived from --gnomad-version: "
                          "0.0001 for v2exome, 0.0005 for v4exome/v4genome. "
                          "If --gnomad-version is also unspecified, the pipeline's "
                          "own default (0.0005) applies.")
    opt.add_argument("--acan-config", default="",
                     help="Path to the ACAN configuration file specifying ancestry groups for analysis. "
                          "Defaults to the file inside --control-data-folder "
                          "(<control-data-folder>/stratified_config_gnomadV4.asj.txt). "
                          "Override only if you need a custom ancestry stratification config.")
    opt.add_argument("--variant-exclude", default="",
                     help="Path to a one-column file of variants to exclude from analysis. "
                          "Defaults to the file inside --control-data-folder "
                          "(<control-data-folder>/gnomAD41WGSExtraExcludeInCodingExcludeTAS2R46.txt.gz). "
                          "Override only if you need a custom exclusion list.")
    opt.add_argument("--chr-set", default="",
                     help="Space-separated list of chromosomes to process (no 'chr' prefix). "
                          "Pipeline default: '1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22'. "
                          "To test on a subset use e.g. '21 22'. "
                          "Note: chromosome names must NOT have a chr prefix.")

    # --- Nextflow execution ---
    nf = parser.add_argument_group("Nextflow execution")
    nf.add_argument("--repo-path", required=True,
                    help="Local path to the cloned nf-core/rarevariantburden repository "
                         "(must contain main.nf). The pipeline is in development and cannot "
                         "be run via 'nf-core/rarevariantburden' shorthand.")
    nf.add_argument("--nextflow-bin", default="nextflow",
                    help="Path to Nextflow executable")
    nf.add_argument("--profile", default="singularity",
                    help="Nextflow profile(s), e.g. 'singularity' or 'singularity,institute'")
    nf.add_argument("--params-config-name", default="rarevariantburden.params.generated.yaml",
                    help="Generated params YAML filename under outdir")
    nf.add_argument("--use-generated-params-file", action="store_true",
                    help="Pass generated params YAML via -params-file instead of CLI flags")
    nf.add_argument("--resume", action="store_true",
                    help="Add -resume to Nextflow command")
    nf.add_argument("--with-report", default="",
                    help="Path for Nextflow -with-report HTML output")
    nf.add_argument("--with-dag", default="",
                    help="Path for Nextflow -with-dag output")
    nf.add_argument("--extra-args", default="",
                    help="Extra raw args appended to Nextflow command")

    # --- Directories ---
    dirs = parser.add_argument_group("Directories")
    dirs.add_argument("--workdir", default="",
                      help="Nextflow work directory (default: <outdir>/work)")
    dirs.add_argument("--logdir", default="",
                      help="Optional scheduler log directory")
    dirs.add_argument("--stdout-file", default="out%J.out",
                      help="Scheduler stdout filename pattern")
    dirs.add_argument("--stderr-file", default="err%J.err",
                      help="Scheduler stderr filename pattern")
    dirs.add_argument("--script-path", default="",
                      help="Launch script path (default: <outdir>/run_rarevariantburden.<executor>.sh)")

    # --- Scheduler ---
    sched = parser.add_argument_group("Scheduler / executor")
    sched.add_argument("--executor", default="local",
                       choices=["local", "none", "lsf", "slurm", "pbs", "sge"],
                       help="Execution backend")
    sched.add_argument("--job-name", default="rarevariantburden",
                       help="Scheduler job name")
    sched.add_argument("--project", default="",
                       help="Scheduler project/account")
    sched.add_argument("--queue", default="",
                       help="Scheduler queue/partition")
    sched.add_argument("--cpus", type=int, default=16,
                       help="CPU slots/threads")
    sched.add_argument("--memory-gb", type=float, default=64.0,
                       help="Requested memory in GB")
    sched.add_argument("--walltime", default="48:00",
                       help="Requested walltime in HH:MM or HH:MM:SS")

    # --- Runtime ---
    rt = parser.add_argument_group("Runtime environment")
    rt.add_argument("--nxf-opts", default="",
                    help="Optional NXF_OPTS, e.g. '-Xms1g -Xmx4g'")
    rt.add_argument("--singularity-cache", default="",
                    help="Optional path exported as NXF_SINGULARITY_CACHEDIR before launching "
                         "Nextflow. Singularity/Apptainer will cache pulled images here so they "
                         "are reused across runs. "
                         "Example: /research/rgs01/home/clusterHome/stithi/singularity-cache")
    rt.add_argument("--conda-env", default="rarevariantburden-nextflow",
                    help="Conda environment name used to resolve Nextflow runtime")
    rt.add_argument("--conda-env-file", default="",
                    help="Conda environment YAML used with --create-conda-env")
    rt.add_argument("--create-conda-env", action="store_true",
                    help="Create conda environment when missing")
    rt.add_argument("--use-current-path", action="store_true",
                    help="Use current PATH and skip conda runtime resolution")
    rt.add_argument("--module-load", default="",
                    help="Optional module command, e.g. 'module load nextflow/23.10.0'")

    # --- Run modes ---
    modes = parser.add_argument_group("Run modes")
    modes.add_argument("--dry-run", action="store_true",
                       help="Validate inputs and write artifacts without execution")
    modes.add_argument("--run", action="store_true",
                       help="Execute or submit the generated launch script")
    modes.add_argument("--submit", action="store_true",
                       help="Backward-compatible alias for --run")

    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = parse_args()

    if args.submit:
        args.run = True

    args.af_max = resolve_af_max(args)

    args.runtime_prefix = None
    args.generated_params_path = ""

    runtime_prefix = resolve_runtime(args)
    if runtime_prefix is not None:
        args.runtime_prefix = str(runtime_prefix)

    # Apply NXF_SINGULARITY_CACHEDIR to the current process environment now
    # so it is inherited by any subprocess launched directly (local executor).
    # The generated shell script also exports it for scheduler submissions.
    if args.singularity_cache:
        os.environ["NXF_SINGULARITY_CACHEDIR"] = args.singularity_cache
        info(f"NXF_SINGULARITY_CACHEDIR set to: {args.singularity_cache}")

    validate_inputs(args)
    ensure_runtime_tools(args)
    ensure_dependency_tools(args)

    os.makedirs(args.outdir, exist_ok=True)
    args.workdir = args.workdir or os.path.join(args.outdir, "work")

    launch_script_path = args.script_path or default_script_path(args)

    if args.logdir:
        os.makedirs(args.logdir, exist_ok=True)
    os.makedirs(os.path.dirname(launch_script_path) or ".", exist_ok=True)

    generated_params_path = write_params_file(args)
    args.generated_params_path = generated_params_path

    nextflow_cmd = build_nextflow_command(args, generated_params_path)
    write_launch_script(args, launch_script_path, nextflow_cmd)

    submit_cmd = submit_command_for_executor(args.executor, launch_script_path)

    print("--- RareVariantBurden Launch Assets Prepared ---")
    print(f"Repo path    : {args.repo_path}")
    print(f"Params YAML  : {os.path.abspath(generated_params_path)}")
    print(f"Launch script: {os.path.abspath(launch_script_path)}")
    print(f"Executor     : {args.executor}")
    print(f"Run cmd      : {submit_cmd}")
    print(f"Reference    : {args.reference}")
    if args.gnomad_version:
        print(f"gnomAD ver   : {args.gnomad_version}")
    if args.af_max is not None:
        print(f"AFMax        : {args.af_max}")
    if args.singularity_cache:
        print(f"Singularity$ : NXF_SINGULARITY_CACHEDIR={args.singularity_cache}")

    if args.dry_run and not args.run:
        info("Dry run complete. Inputs and runtime dependencies validated.")
        return

    if not args.run:
        info("Artifacts generated. Re-run with --run to execute/submit.")
        return

    execute_launch(args, launch_script_path)


if __name__ == "__main__":
    main()
