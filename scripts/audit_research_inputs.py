"""Inspect local saved inputs read-only. Private details stay under ignored data/."""
import argparse
from datetime import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from src.research_readiness import audit_workbench
from src.workbench import DEFAULT_PATH


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workbench',default=str(DEFAULT_PATH))
    parser.add_argument('--as-of',default=str(datetime.now(ZoneInfo('Asia/Shanghai')).date()))
    parser.add_argument('--output',default='data/research-input-audit.json')
    args=parser.parse_args()
    result=audit_workbench(args.workbench,as_of=args.as_of)
    target=Path(args.output)
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    # Never print company identifiers, raw figures, provider bodies or keys.
    print(json.dumps({k:result[k] for k in ('as_of','company_count','saved_versions_checked','forward_ready','archive_ready')},ensure_ascii=False))


if __name__=='__main__':
    main()
