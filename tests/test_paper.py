import unittest
from datetime import date
import market,paper

def quote(code='600001',price=5.,opened=5.,day='20261029',name='样本'):
 return dict(code=code,name=name,price=price,prev=5.,open=opened,volume=100000,cap=1e9,timestamp=day+'093100',upper=5.5,lower=4.5,high=price,low=price)
def ready():
 s=paper.initial();s['pending_entry']=dict(signal_date='2026-10-28',buy_date='2026-10-29',candidates=[quote()],cycle='STARTUP_EXCEPTION');return s
class Rules(unittest.TestCase):
 def test_calendar(self):
  self.assertFalse(market.trading_day(date(2026,10,7)));self.assertTrue(market.trading_day(date(2026,10,29)));self.assertTrue(market.month_end(date(2026,10,30)));self.assertEqual(market.next_day(date(2026,10,30)),date(2026,11,2))
 def test_fees(self):
  self.assertEqual(paper.fee(4000,'B'),dict(commission=5.,stamp=0.,transfer=.04));self.assertEqual(paper.fee(100000,'S'),dict(commission=10.,stamp=10.,transfer=1.))
 def test_cash_and_idempotence(self):
  s=ready();q={'600001':quote()};paper.buy(s,date(2026,10,29),q,'obs');self.assertEqual(s['positions']['600001']['qty'],39900);self.assertEqual(s['cash'],478.05);n=len(s['orders']);paper.buy(s,date(2026,10,29),q,'obs2');self.assertEqual(len(s['orders']),n)
 def test_t1_and_closing(self):
  s=ready();q={'600001':quote()};paper.buy(s,date(2026,10,29),q,'obs');paper.sell(s,date(2026,10,29),q,'obs',True);self.assertIn('600001',s['positions']);q={'600001':quote(day='20261030')};paper.sell(s,date(2026,10,30),q,'obs',True);self.assertFalse(s['positions']);self.assertEqual(s['cash'],199936.15)
 def test_limits_and_stale(self):
  for r in [quote(opened=5.5),quote(day='20261028'),quote(name='*ST样本')]:
   s=ready();paper.buy(s,date(2026,10,29),{'600001':r},'obs');self.assertFalse(s['positions']);self.assertEqual(s['cash'],200000)
 def test_downlimit_keeps_cash_occupied(self):
  s=ready();paper.buy(s,date(2026,10,29),{'600001':quote()},'obs');r=quote(price=4.5,day='20261030');paper.sell(s,date(2026,10,30),{'600001':r},'obs',True);self.assertIn('600001',s['pending_exits']);self.assertEqual(s['cash'],478.05)
 def test_ranks_before_filter_no_refill(self):
  q={f'600{i:03d}':quote(f'600{i:03d}',price=1.+i/1000,day='20261028') for i in range(1,202)}
  # The >2 stock sits beyond price rank 200 and must not be substituted.
  q['600201']['price']=3.;listing={c:'2000-01-01' for c in q};chosen,_,_=market.screen(q,date(2026,10,28),listing);self.assertEqual(chosen,[])
 def test_no_new_shares_dividend(self):
  s=ready();paper.buy(s,date(2026,10,29),{'600001':quote()},'obs');before=s['cash'];ev={'SECURITY_CODE':'600001','BONUS_IT_RATIO':0,'PRETAX_BONUS_RMB':1.}
  paper.apply_dividends(s,date(2026,10,30),[ev]);paper.apply_dividends(s,date(2026,10,30),[ev]);self.assertEqual(s['cash'],paper.money(before+3990));self.assertEqual(s['positions']['600001']['dividends'],3990)
if __name__=='__main__':unittest.main()
