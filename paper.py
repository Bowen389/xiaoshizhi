"""Deterministic local paper account. No broker or notification interface."""
from datetime import date
from calendar import monthrange
from decimal import Decimal,ROUND_HALF_UP
import market

def money(v):return float(Decimal(str(float(v))).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))
def fee(v,side):return dict(commission=money(max(5,v*.0001)),stamp=money(v*.0001) if side=='S' else 0.,transfer=money(v*.00001))
def initial():return dict(schema=1,mode='PAPER_ONLY',initial=200000.,cash=200000.,positions={},orders=[],events=[],processed=[],pending_exits=[],pending_entry=None,nav=[],corporate_done=[],started='2026-10-28',startup_buy='2026-10-29')
def record(s,event):s['events'].append(event)

def quantities(budget,price):
 qty=int(budget/price/100)*100
 while qty>0:
  value=money(qty*price)
  if value+sum(fee(value,'B').values())<=budget:return qty
  qty-=100
 return 0

def apply_dividends(s,day,events):
 key=day.isoformat()
 if key in s['corporate_done']:return
 for ev in events:
  c=ev['SECURITY_CODE']
  if c not in s['positions']:continue
  v=s['positions'][c]
  if v['buy_date']>=key:continue
  ratio=1+float(ev.get('BONUS_IT_RATIO') or 0)/10
  if ratio!=1:raise ValueError('送转事件需核验上市日及零股处理，停止本次记账 '+c)
  value=money(v['qty']*float(ev.get('PRETAX_BONUS_RMB') or 0)/10);s['cash']=money(s['cash']+value);v['dividends']=money(v['dividends']+value)
  record(s,dict(date=key,kind='cash_dividend',code=c,amount=value,pay_basis='ex_date_assumption'))
 s['corporate_done'].append(key)

def sell(s,day,q,observed,monthly=False):
 stamp=day.isoformat();targets=set(s['pending_exits'])
 if monthly:targets.update(s['positions'])
 s['pending_exits']=sorted(targets)
 for c in sorted(targets):
  if c not in s['positions']:
   s['pending_exits'].remove(c);continue
  v=s['positions'][c];key=stamp+':S:'+c
  if key in s['processed']:continue
  r=q.get(c)
  if not r or not market.active(r,day):
   record(s,dict(date=stamp,kind='sell_blocked',code=c,reason='停牌/缺失/非当日行情'));continue
  px=r['price'] if monthly else r['open']
  if v['buy_date']>=stamp or px<=0 or r['lower']<=0 or px<=r['lower']+.001:
   record(s,dict(date=stamp,kind='sell_blocked',code=c,reason='T+1/跌停/无价格限制字段'));continue
  value=money(v['qty']*px);cost=fee(value,'S');bd=date.fromisoformat(v['buy_date']);month=date(bd.year+bd.month//12,bd.month%12+1,min(bd.day,monthrange(bd.year+bd.month//12,bd.month%12+1)[1]));year=bd.replace(year=bd.year+1,day=min(bd.day,monthrange(bd.year+1,bd.month)[1]));rate=.2 if day<=month else (.1 if day<=year else 0);dtax=money(v['dividends']*rate)
  net=money(value-sum(cost.values())-dtax);s['cash']=money(s['cash']+net);pnl=money(net+v['dividends']-v['entry_cost'])
  s['orders'].append(dict(id=key,date=stamp,code=c,name=v['name'],side='S',qty=v['qty'],price=px,value=value,**cost,dividend_tax=dtax,observed_at=observed,fill_basis='closing_price_model' if monthly else 'opening_price_model',buy_date=v['buy_date'],pnl=pnl))
  del s['positions'][c];s['pending_exits'].remove(c);s['processed'].append(key)

def buy(s,day,q,observed):
 stamp=day.isoformat();target=s.get('pending_entry')
 if not target or target['buy_date']!=stamp:return
 key=stamp+':ENTRY:'+target['signal_date']
 if key in s['processed']:return
 candidates=target['candidates'];budget=s['cash']/len(candidates) if candidates else 0.
 for cand in candidates:
  c=cand['code'];r=q.get(c);reason=None
  if c in s['positions']:reason='旧仓未卖出，不加仓'
  elif not r or not market.active(r,day):reason='停牌/缺失/非当日行情'
  elif 'ST' in r['name'].upper() or '退' in r['name']:reason='买入日ST/退市'
  elif r['open']<=0 or r['upper']<=0 or r['open']>=r['upper']-.001:reason='无开盘价/涨停/限制字段缺失'
  if reason:
   record(s,dict(date=stamp,kind='buy_blocked',code=c,reason=reason));continue
  px=r['open'];qty=quantities(min(budget,s['cash']),px)
  if qty<=0:
   record(s,dict(date=stamp,kind='buy_blocked',code=c,reason='不足整手及费用'));continue
  value=money(qty*px);cost=fee(value,'B');entry=money(value+sum(cost.values()));s['cash']=money(s['cash']-entry)
  s['positions'][c]=dict(code=c,name=r['name'],qty=qty,buy_date=stamp,buy_price=px,entry_cost=entry,dividends=0.,last_price=px,last_quote_date=stamp)
  oid=stamp+':B:'+c+':'+target['signal_date'];s['orders'].append(dict(id=oid,date=stamp,code=c,name=r['name'],side='B',qty=qty,price=px,value=value,**cost,dividend_tax=0.,signal_date=target['signal_date'],signal_price=cand['price'],observed_at=observed,fill_basis='opening_price_model',cycle=target['cycle']))
  s['processed'].append(oid)
 s['processed'].append(key);target['attempted']=True

def mark(s,day,q,observed):
 for c,v in s['positions'].items():
  r=q.get(c)
  if r and market.active(r,day):v['last_price']=r['price'];v['last_quote_date']=day.isoformat()
 mv=money(sum(v['qty']*v['last_price'] for v in s['positions'].values()));equity=money(s['cash']+mv)
 item=dict(date=day.isoformat(),observed_at=observed,cash=s['cash'],market_value=mv,equity=equity,return_pct=round((equity/200000-1)*100,4),holdings=len(s['positions']),stale_codes=[c for c,v in s['positions'].items() if v['last_quote_date']!=day.isoformat()])
 s['nav']=[n for n in s['nav'] if n['date']!=day.isoformat()]+[item]
 assert s['cash']>=0 and len({o['id'] for o in s['orders']})==len(s['orders'])
 return item
