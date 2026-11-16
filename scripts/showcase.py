"""Showcase trials for the site and the video: a court staffed by one model on chosen docket cases.
These are demonstrations, labelled as such; the evaluation is in results/e1.json. Usage: showcase.py MODEL CASE_ID..."""
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import docket
from court.trial import run_trial

OUT = Path(__file__).resolve().parents[1] / "results" / "showcase"
OUT.mkdir(parents=True, exist_ok=True)
model, ids = sys.argv[1], sys.argv[2:]
for cid in ids:
    dc = docket.load_case(cid)
    case, world, log = getattr(dc, "case", dc), docket.world_for(dc), docket.log_for(dc)
    from court.types import CaseFile
    if not isinstance(case, CaseFile):
        case = CaseFile.model_validate({k: case[k] for k in ("case_id", "world_id", "spec", "claim", "requested_capital", "log_summary", "pages_read") if k in case})
    t = time.time()
    rec = run_trial(case, world, log, system="court", staffing={"default": model})
    tag = model.replace(":", "_").replace("/", "_")
    (OUT / f"{cid}__{tag}.json").write_text(rec.model_dump_json(indent=1))
    print(cid, rec.verdict.ruling, [(e.id, e.test, e.hint) for e in rec.exhibits], f"{time.time()-t:.0f}s", flush=True)
