"""Public mainland market data; stdlib only, no import os."""
import csv,hashlib,json,time,urllib.parse,urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date,datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
TZ=ZoneInfo('Asia/Shanghai');PREFIX=('600','601','603','605','000','001','002','003')
HOLIDAYS={2026:[('01-01','01-03'),('02-15','02-23'),('04-04','04-06'),('05-01','05-05'),('06-19','06-21'),('09-25','09-27'),('10-01','10-07')]}

def now():return datetime.now(TZ)
def trading_day(d):
 if d.year not in HOLIDAYS:raise ValueError('交易日历未覆盖%s年，需先更新官方休市安排'%d.year)
 return d.weekday()<5 and not any(date.fromisoformat(f'{d.year}-{a}')<=d<=date.fromisoformat(f'{d.year}-{b}') for a,b in HOLIDAYS[d.year])
def next_day(d):
 d+=timedelta(days=1)
 while not trading_day(d):d+=timedelta(days=1)
 return d
def month_end(d):
 # Test only the remainder of the current month; no invented next-year holidays.
 n=d+timedelta(days=1)
 while n.month==d.month:
  if trading_day(n):return False
  n+=timedelta(days=1)
 return True

def request(url,encoding='utf-8'):
 for attempt in range(3):
  try:
   with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=30) as r:return r.read().decode(encoding)
  except Exception:
   if attempt==2:raise
   time.sleep(attempt+1)

def dc(report,fields,flt,pagesize=500,sort=None,first_only=False):
 rows=[]
 for page in range(1,40):
  args=dict(reportName=report,columns=fields,filter=flt,pageSize=pagesize,pageNumber=page)
  if sort:args.update(sortColumns=sort,sortTypes=-1)
  j=json.loads(request('https://datacenter-web.eastmoney.com/api/data/v1/get?'+urllib.parse.urlencode(args)))
  if not j.get('result'):
   if j.get('message')=='返回数据为空' or j.get('code')==9201:return rows
   raise ValueError('数据源异常: '+str(j)[:180])
  rows.extend(j['result']['data'])
  if first_only:return rows
  if page>=j['result']['pages']:
   if j['result'].get('count',len(rows))!=len(rows):raise ValueError('分页不完整')
   return rows
 raise ValueError('分页超过上限')

def universe(today):
 row=dc('RPT_VALUEANALYSIS_DET','SECURITY_CODE,TRADE_DATE','(SECURITY_CODE="600000")',1,'TRADE_DATE',True)[0]
 d=row['TRADE_DATE'][:10]
 if d>today.isoformat() or (today-date.fromisoformat(d)).days>7:raise ValueError('股票池日期异常 '+d)
 rows=dc('RPT_VALUEANALYSIS_DET','SECURITY_CODE,TRADE_DATE',"(TRADE_DATE='%s')"%d)
 codes=sorted({r['SECURITY_CODE'] for r in rows if r['SECURITY_CODE'].startswith(PREFIX)})
 if len(codes)<3000:raise ValueError('主板股票池异常偏少: %s'%len(codes))
 return codes,d

def parse_quotes(text):
 rows={}
 for line in text.split(';'):
  if '~' not in line:continue
  f=line.split('"')[1].split('~')
  if len(f)<49:continue
  try:
   c=f[2];rows[c]=dict(code=c,name=f[1],price=float(f[3]),prev=float(f[4]),open=float(f[5]),volume=float(f[6])*100,timestamp=f[30],high=float(f[33]),low=float(f[34]),cap=float(f[45])*1e8,upper=float(f[47]),lower=float(f[48]))
  except (ValueError,IndexError):continue
 return rows

def quotes(codes):
 def batch(cc):
  syms=[('sh' if c.startswith('6') else 'sz')+c for c in cc]
  # Indices are only requested explicitly by the caller, never in universe ranks.
  return parse_quotes(request('https://qt.gtimg.cn/q='+','.join(syms),'gbk'))
 batches=[codes[i:i+70] for i in range(0,len(codes),70)];out={}
 with ThreadPoolExecutor(max_workers=5) as pool:
  for r in pool.map(batch,batches):out.update(r)
 missing=set(codes)-set(out)
 if missing:raise ValueError('行情缺失，不在残缺股票池上排名: '+','.join(sorted(missing)))
 return out

def quote_date(r):
 ts=r.get('timestamp','')
 return f'{ts[:4]}-{ts[4:6]}-{ts[6:8]}' if len(ts)>=14 and ts[:8].isdigit() else None

def active(r,day):return quote_date(r)==day.isoformat() and r['volume']>0 and r['price']>0

def listing_dates(codes):
 if not codes:return {}
 flt='(SECURITY_CODE in ('+','.join('"'+c+'"' for c in codes)+'))'
 rows=dc('RPT_F10_ORG_BASICINFO','SECURITY_CODE,LISTING_DATE',flt)
 result={r['SECURITY_CODE']:r['LISTING_DATE'][:10] for r in rows if r.get('LISTING_DATE')}
 if set(codes)-set(result):raise ValueError('上市日期缺失')
 return result

def screen(q,day,listed):
 valid=[r for c,r in q.items() if c.startswith(PREFIX) and r['price']>0 and r['cap']>0]
 price=sorted(valid,key=lambda r:(r['price'],r['code']))[:200];small=sorted(valid,key=lambda r:(r['cap'],r['code']))[:200];caps={r['code'] for r in small}
 common=[r for r in price if r['code'] in caps];chosen=[];excluded=[]
 for r in common:
  c=r['code'];reason=[]
  if r['price']<=2:reason.append('价格不大于2元')
  if 'ST' in r['name'].upper():reason.append('当前ST')
  if '退' in r['name']:reason.append('当前退市/退市整理')
  if not active(r,day):reason.append('停牌或非当日行情')
  if c not in listed:reason.append('上市日期未核验')
  elif (day-date.fromisoformat(listed[c])).days<365:reason.append('上市未满365天')
  if reason:excluded.append(dict(code=c,name=r['name'],reasons=reason))
  else:chosen.append(dict(r,listed_date=listed[c]))
 return sorted(chosen,key=lambda r:r['code']),excluded,len(valid)

def scan(day,root):
 codes,source_day=universe(day);q=quotes(codes)
 # Date freshness of broad universe: stale suspended quotes remain ranked but excluded afterwards.
 if sum(active(r,day) for r in q.values())<.9*len(codes):raise ValueError('当日有效行情不足90%，不能封存信号')
 valid=[r for r in q.values() if r['price']>0 and r['cap']>0]
 ranked=sorted(valid,key=lambda r:(r['price'],r['code']))[:200]
 tiny={r['code'] for r in sorted(valid,key=lambda r:(r['cap'],r['code']))[:200]}
 common=[r['code'] for r in ranked if r['code'] in tiny]
 listed=listing_dates(common);chosen,excluded,count=screen(q,day,listed)
 raw=json.dumps(q,ensure_ascii=False,sort_keys=True,separators=(',',':'));digest=hashlib.sha256(raw.encode()).hexdigest()
 folder=root/'data'/'inputs';folder.mkdir(parents=True,exist_ok=True)
 with (folder/(day.isoformat()+'_'+digest[:12]+'_universe.csv')).open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=['code','name','price','prev','open','volume','cap','timestamp','upper','lower','high','low']);w.writeheader();w.writerows(q.values())
 return dict(input_file='data/inputs/'+day.isoformat()+'_'+digest[:12]+'_universe.csv',date=day.isoformat(),observed_at=now().isoformat(),universe_source_date=source_day,universe_count=len(codes),valid_rank_count=count,universe_sha256=digest,candidates=chosen,excluded=excluded,source='腾讯当日行情：票面价/总市值；东方财富：股票池/上市日',basis='close' if now().hour>=15 else 'intraday_observation',_quotes=q)

def dividends(codes,day):
 if not codes:return []
 flt='(SECURITY_CODE in ('+','.join('"'+c+'"' for c in codes)+'))'+"(EX_DIVIDEND_DATE='%s')"%day.isoformat()
 return [r for r in dc('RPT_SHAREBONUS_DET','SECURITY_CODE,EX_DIVIDEND_DATE,PRETAX_BONUS_RMB,BONUS_IT_RATIO,ASSIGN_PROGRESS',flt) if r['ASSIGN_PROGRESS']=='实施分配']
