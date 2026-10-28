"""Run daily public-data screen and 200k paper model, never broker orders."""
import argparse,csv,json,sys,traceback
from pathlib import Path
import market,paper
ROOT=Path(__file__).resolve().parent

def write_json(path,value):
 path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_suffix(path.suffix+'.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');temp.replace(path)

def save(s):
 write_json(ROOT/'data'/'account.json',s)
 for name,rows in [('orders',s['orders']),('nav',s['nav'])]:
  path=ROOT/'data'/(name+'.csv');keys=list(dict.fromkeys(k for r in rows for k in r))
  with path.open('w',newline='') as f:
   if keys:
    w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(rows)

def render(s,signal,phase,observed):
 nav=s['nav'][-1] if s['nav'] else dict(cash=s['cash'],equity=s['cash'],market_value=0,return_pct=0)
 target=s.get('pending_entry');lines=['# 原始双低200/200：20万元模拟账户','',f'更新时间：{observed}；阶段：{phase}。','',f"现金：{nav['cash']:,.2f}元；持仓市值：{nav['market_value']:,.2f}元；总资产：{nav['equity']:,.2f}元；收益：{nav['return_pct']:.4f}%。",'', '**仅开收盘价模型模拟，不连接券商。** GitHub排队延迟时，可在当日收盘任务补记同日开盘价模型成交，observed_at保留真实观测时间，不冒充即时下单。','']
 if target:lines +=[f"待执行信号：{target['signal_date']}；计划买入：{target['buy_date']}；周期：{target['cycle']}；已尝试：{target.get('attempted',False)}。",'']
 if signal:
  lines +=[f"今日筛选：{signal['date']}，主板股票池{signal['universe_count']}只；有效排名{signal['valid_rank_count']}只；最终候选{len(signal['candidates'])}只。",'', '| 代码 | 名称 | 信号价格 | 总市值（亿元） |','|---|---|---:|---:|']
  lines +=[f"| {r['code']} | {r['name']} | {r['price']:.2f} | {r['cap']/1e8:.2f} |" for r in signal['candidates']]
 lines +=['','## 持仓','','| 代码 | 名称 | 股数 | 买入日 | 买入价 | 最新估值价 |','|---|---|---:|---|---:|---:|']
 lines +=[f"| {c} | {p['name']} | {p['qty']} | {p['buy_date']} | {p['buy_price']:.2f} | {p['last_price']:.2f} |" for c,p in s['positions'].items()]
 lines +=['','## 启动与月度工作流','','- 2026-10-28收盘：封存启动期候选。','- 2026-10-29：以开盘价模型模拟买入，初始资金200000元。','- 2026-10-30收盘：卖出启动期仓位（卖不出继续持有），封存正式月末信号。','- 2026-11-02：按10月30日信号开盘价模型买入，恢复月末持有/轮动。','','信号先分别取价格最低200和总市值最小200交集，再过滤股价≤2元、ST/*ST、退市、停牌、上市未满365日；不补位。买卖佣金各万一、每笔最低5元；卖出自定义印花税万一；双向过户费0.01‰。','', '数据：[账户](../data/account.json) · [模拟委托](../data/orders.csv) · [净值](../data/nav.csv) · [封存信号](../data/signals/)。']
 p=ROOT/'reports'/'latest.md';p.parent.mkdir(exist_ok=True);p.write_text('\n'.join(lines)+'\n')

def run(phase):
 clock=market.now();day=clock.date();stamp=day.isoformat();observed=clock.isoformat();p=ROOT/'data'/'account.json';s=json.loads(p.read_text()) if p.exists() else paper.initial()
 if not market.trading_day(day):
  render(s,None,'休市，无交易',observed);print('休市',stamp);return
 if phase=='auto':phase='close' if (clock.hour,clock.minute)>=(15,10) else ('watch' if (clock.hour,clock.minute)>=(9,30) else 'preflight')
 if phase=='preflight':render(s,None,phase,observed);print('盘前检查；未模拟买入');return
 if (clock.hour,clock.minute)<(9,30):raise ValueError('尚未开盘，不能创建当日开盘价模拟成交')
 if phase=='close' and (clock.hour,clock.minute)<(15,10):raise ValueError('尚未收盘，不能封存收盘信号或按收盘价卖出')
 signal=None;q={}
 if phase=='close':
  observed_signal=market.scan(day,ROOT);q=observed_signal.pop('_quotes')
  path=ROOT/'data'/'signals'/(stamp+'.json')
  if path.exists():
   signal=json.loads(path.read_text())
   if signal['universe_sha256']!=observed_signal['universe_sha256']:
    print('同日源数据更新；保留已封存信号，不改动明日候选。')
  else:signal=observed_signal
 else:
  codes=set(s['positions'])
  if s.get('pending_entry'):codes.update(c['code'] for c in s['pending_entry']['candidates'])
  if codes:q=market.quotes(sorted(codes))
 observed=market.now().isoformat()
 # Corporate action query runs once per day for existing holdings. Failure aborts atomically.
 if stamp not in s['corporate_done']:
  paper.apply_dividends(s,day,market.dividends(sorted(s['positions']),day))
 # Opening phase or same-day delayed replay. State IDs prevent duplicate fills.
 paper.sell(s,day,q,observed,monthly=False)
 paper.buy(s,day,q,observed)
 if phase=='close' and market.month_end(day):paper.sell(s,day,q,observed,monthly=True)
 nav=paper.mark(s,day,q,observed)
 if signal:
  # Freeze signal first, so a retry cannot replace a previously scheduled cohort.
  path=ROOT/'data'/'signals'/(stamp+'.json')
  if not path.exists():write_json(path,signal)
  if day.isoformat()==s['started'] and not s.get('startup_prepared'):
   s['pending_entry']=dict(signal_date=stamp,buy_date=s['startup_buy'],candidates=signal['candidates'],cycle='STARTUP_EXCEPTION',attempted=False);s['startup_prepared']=True
  elif market.month_end(day):
   due=market.next_day(day).isoformat()
   if not s.get('pending_entry') or s['pending_entry']['signal_date']!=stamp:
    s['pending_entry']=dict(signal_date=stamp,buy_date=due,candidates=signal['candidates'],cycle='MONTHLY_ORIGINAL',attempted=False)
  write_json(ROOT/'data'/'latest_screen.json',signal)
 write_json(ROOT/'data'/'quotes'/(stamp+'.json'),dict(date=stamp,observed_at=observed,quotes={c:r for c,r in q.items() if c in s['positions'] or (s.get('pending_entry') and c in {x['code'] for x in s['pending_entry']['candidates']})}))
 save(s);render(s,signal,phase,observed);(ROOT/'reports'/'last_error.json').unlink(missing_ok=True);print(json.dumps(dict(phase=phase,date=stamp,candidates=len(signal['candidates']) if signal else None,nav=nav),ensure_ascii=False))

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=['auto','preflight','open','watch','close'],default='auto');args=parser.parse_args()
 try:run(args.phase)
 except Exception as exc:
  write_json(ROOT/'reports'/'last_error.json',dict(observed_at=market.now().isoformat(),error=str(exc),status='FAILED_NO_ACCOUNT_COMMIT'))
  traceback.print_exc();sys.exit(1)
