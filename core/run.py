# Runs the data pipeline's stages in order, from the repo root. Standard library only.
#
#   uv run core/run.py               every stage whose inputs are present
#   uv run core/run.py clean pdf     only these stages, in pipeline order
#   uv run core/run.py --list        the stages, their inputs and outputs
#
# A stage whose input file is missing is skipped with a note (the guide PDF is not in git), unless
# it was named on the command line, when that is an error. A stage that fails stops the run. The last
# stage, check, validates every data file against the schemas in core/schemas/.
# Loading into Supabase is not a stage here: it writes to a shared database, so it stays a
# separate, deliberate command (npm run import).

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = "data"


@dataclass(frozen=True)
class Stage:
    name: str
    what: str
    needs: tuple[str, ...]      # input files, relative to the repo root
    writes: tuple[str, ...]     # output files, for --list
    commands: tuple[tuple[str, ...], ...]


STAGES = (
    Stage("clean", "clean the Connections Guide export",
          (f"{DATA}/NYPL Connections Resources.csv", f"{DATA}/NYPLConnections_NoMatch.csv"),
          (f"{DATA}/cleaned/resources_clean.csv", f"{DATA}/cleaned/review_list.csv"),
          (("uv", "run", "core/pipeline/clean_guide.py"),)),
    Stage("pdf", "extend it with the printed guide PDF",
          (f"{DATA}/NYPL_JPS_Connections_2026.pdf", f"{DATA}/cleaned/resources_clean.csv"),
          (f"{DATA}/extracted/connections_pdf_listings.csv", f"{DATA}/extracted/connections_pdf_vs_csv.csv",
           f"{DATA}/cleaned/resources_extended.csv"),
          (("uv", "run", "core/pipeline/extract_pdf.py"),
           ("uv", "run", "core/pipeline/match_pdf.py"),
           ("uv", "run", "core/pipeline/extend_with_pdf.py"))),
    Stage("geocode", "add coordinates (NYC GeoSearch, then Census; needs the network)",
          (f"{DATA}/NYPL Connections Resources.csv",),
          (f"{DATA}/nypl_connections_resources.geojson",),
          (("uv", "run", "core/pipeline/geocode.py"),)),
    Stage("audiences", "tag who each resource serves, then check the result",
          (f"{DATA}/cleaned/resources_extended.csv", f"{DATA}/extracted/connections_pdf_listings.csv",
           f"{DATA}/nypl_connections_resources.geojson"),
          (f"{DATA}/cleaned/resource_audiences.csv", f"{DATA}/review/audience_review.csv",
           f"{DATA}/review/audience_no_match.csv"),
          (("uv", "run", "core/pipeline/tag_audiences.py"),
           ("uv", "run", "core/pipeline/check_audiences.py"))),
    Stage("ids", "give every row a stable id, kept in data/resource_ids.csv",
          (f"{DATA}/nypl_connections_resources.geojson", f"{DATA}/cleaned/resources_extended.csv",
           f"{DATA}/cleaned/resource_audiences.csv"),
          (f"{DATA}/resource_ids.csv",),
          (("uv", "run", "core/pipeline/resource_ids.py", "--write"),)),
    Stage("build", "write the files the site reads to data/public/",
          (f"{DATA}/resource_ids.csv",),
          (f"{DATA}/public/resources.public.json", f"{DATA}/public/resources.provenance.json",
           f"{DATA}/review/needs_address.csv"),
          (("uv", "run", "core/pipeline/build_data.py", "--write"),)),
    Stage("check", "check every data file against its schema in core/schemas/",
          (),
          (),
          (("uv", "run", "core/pipeline/check_data.py"),)),
)


def list_stages():
    for s in STAGES:
        print(f"{s.name:10} {s.what}")
        print(f"{'':10}   reads  {', '.join(s.needs) or '-'}")
        print(f"{'':10}   writes {', '.join(s.writes) or '-'}")


def run(stage):
    for command in stage.commands:
        print(f"$ {' '.join(command)}", flush=True)
        # No __pycache__ folders next to the stage scripts.
        subprocess.run(command, cwd=ROOT, check=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})


def main(argv):
    if "--list" in argv:
        list_stages()
        return 0
    names = [s.name for s in STAGES]
    unknown = [a for a in argv if a not in names]
    if unknown:
        print(f"unknown stage {', '.join(unknown)}; stages are {', '.join(names)}", file=sys.stderr)
        return 2
    wanted = [s for s in STAGES if not argv or s.name in argv]
    for stage in wanted:
        missing = [f for f in stage.needs if not (ROOT / f).exists()]
        if missing:
            if argv:
                print(f"{stage.name}: cannot run, missing {', '.join(missing)}", file=sys.stderr)
                return 1
            print(f"== {stage.name}: skipped, missing {', '.join(missing)}")
            continue
        print(f"== {stage.name}: {stage.what}")
        try:
            run(stage)
        except subprocess.CalledProcessError as e:
            print(f"{stage.name}: {' '.join(e.cmd)} exited with {e.returncode}", file=sys.stderr)
            return e.returncode
    print("Done. To load the result into Supabase: npm run import -- --dry-run, then npm run import")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
