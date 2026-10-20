"""Session-local fictional forward workflow, including an explicit simulation clock."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import json
import tempfile

from src.forward_ledger import ForwardLedger
from src.research_signal_fixtures import demo_manifest
from src.workbench import Workbench


class ForwardDemo:
    def __init__(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='researchpilot-forward-demo-')
        self.store = Workbench(Path(self.temporary.name)/'workbench.db')
        self.clock = datetime(2025,5,2,12,tzinfo=timezone.utc)
        self.manifest = demo_manifest()
        self.symbol = self.manifest['cases'][0]['symbol']
        self.store.watch(self.symbol,'前向研究演示公司（虚构）')
        feature = self.manifest['snapshots'][0]
        self.feature_id = 'demo-forward-feature'
        self._insert(self.feature_id,feature['payload'],'2025-05-01T12:00:00+00:00')
        self.ledger = ForwardLedger(self.store,clock=lambda:self.clock,allow_synthetic=True)

    def _insert(self,key,payload,created):
        with self.store.connect() as db:
            db.execute('INSERT OR IGNORE INTO financial_inputs VALUES (?,?,?,?)',
                       (key,self.symbol,created,json.dumps(payload,ensure_ascii=False,allow_nan=False)))

    def advance(self):
        if self.clock.year<2026:
            self.clock = datetime(2026,5,2,12,tzinfo=timezone.utc)
        outcome = self.manifest['snapshots'][1]
        self._insert('demo-forward-outcome',outcome['payload'],'2026-05-01T12:00:00+00:00')

    def revise(self):
        self.advance()
        self.clock = datetime(2026,5,3,12,tzinfo=timezone.utc)
        outcome = deepcopy(self.manifest['snapshots'][1]['payload'])
        for row in outcome['financial_records']:
            if row['metric']=='revenue' and row['period_end']=='2025-12-31':
                row['value']='80'
        self._insert('demo-forward-revised',outcome,'2026-05-03T11:00:00+00:00')
