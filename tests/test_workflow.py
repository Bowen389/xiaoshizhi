import json,tempfile,unittest
from pathlib import Path
from datetime import datetime
from unittest.mock import patch
import run,market
from test_paper import quote

class Workflow(unittest.TestCase):
 def test_bootstrap_then_monthly_and_restart(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);day='2026-10-28';r=quote(day='20261028');signal=dict(date=day,observed_at=day+'T16:00:00+08:00',universe_source_date=day,universe_count=3194,valid_rank_count=3194,universe_sha256='hash1',candidates=[r],excluded=[],_quotes={'600001':r})
   with patch.object(run,'ROOT',root),patch('market.now',return_value=datetime(2026,10,28,16,0,tzinfo=market.TZ)),patch('market.scan',return_value=signal),patch('market.dividends',return_value=[]):run.run('close')
   s=json.loads((root/'data/account.json').read_text());self.assertEqual(s['cash'],200000);self.assertEqual(s['pending_entry']['buy_date'],'2026-10-29')
   with patch.object(run,'ROOT',root),patch('market.now',return_value=datetime(2026,10,29,9,31,tzinfo=market.TZ)),patch('market.quotes',return_value={'600001':quote()}),patch('market.dividends',return_value=[]):
    run.run('open');run.run('open')
   s=json.loads((root/'data/account.json').read_text());self.assertEqual(len(s['orders']),1);self.assertEqual(s['positions']['600001']['qty'],39900)
   r=quote(day='20261030');sig=dict(date='2026-10-30',observed_at='2026-10-30T16:00:00+08:00',universe_source_date='2026-10-30',universe_count=3194,valid_rank_count=3194,universe_sha256='hash2',candidates=[r],excluded=[],_quotes={'600001':r})
   with patch.object(run,'ROOT',root),patch('market.now',return_value=datetime(2026,10,30,16,0,tzinfo=market.TZ)),patch('market.scan',return_value=sig),patch('market.dividends',return_value=[]):run.run('close')
   s=json.loads((root/'data/account.json').read_text());self.assertEqual(len(s['orders']),2);self.assertEqual(s['pending_entry']['buy_date'],'2026-11-02');self.assertEqual(s['pending_entry']['cycle'],'MONTHLY_ORIGINAL');self.assertFalse(s['positions'])
 def test_source_failure_preserves_account(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);(root/'data').mkdir();body=json.dumps({'initial':200000,'cash':200000});(root/'data/account.json').write_text(body)
   with patch.object(run,'ROOT',root),patch('market.now',return_value=datetime(2026,10,28,16,0,tzinfo=market.TZ)),patch('market.scan',side_effect=ValueError('source failed')):
    with self.assertRaises(ValueError):run.run('close')
   self.assertEqual((root/'data/account.json').read_text(),body)
if __name__=='__main__':unittest.main()
