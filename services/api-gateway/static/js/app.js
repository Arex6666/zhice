"use strict";
/* ============================================================
   智策 ZhiCe · 量化盯盘终端 —— 前端逻辑
   两个视图：① 盯盘墙(board, 默认) ② 个股研判(detail)
   盯盘墙：一次 /api/finance/board 批量行情 → 指数脉搏 + 涨跌家数 + 分行业网格，
           12s 自动刷新、变价闪烁、北京时段感知。点个股 → 进入 detail。
   ============================================================ */

/* ---------------- helpers ---------------- */
function esc(s){ return String(s==null?'':s).replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m])); }
function safeUrl(u){ try{ const x=new URL(u, location.origin); return (x.protocol==='http:'||x.protocol==='https:') ? x.href : null; }catch(e){ return null; } }
function $(id){ return document.getElementById(id); }
function fmt(n, d){ return (n==null || isNaN(n)) ? '—' : Number(n).toFixed(d==null?2:d); }
function pct(n){ return (n==null || isNaN(n)) ? '—' : (Number(n)*100).toFixed(0)+'%'; }
function signed(n, d){ if (n==null || isNaN(n)) return '—'; const v=Number(n); return (v>0?'+':'')+v.toFixed(d==null?2:d); }

async function getJSON(url, opts){
  const r = await fetch(url, opts);
  let data;
  try { data = await r.json(); }
  catch(e){ return { __httperr: true, status: r.status, error: '响应非 JSON（上游可能降级/不可达）' }; }
  if (!r.ok && data && typeof data === 'object' && !data.error) data.__httperr = true;
  return data;
}
function isErr(d){
  return !d || (typeof d === 'object' && !Array.isArray(d) && (d.error || d.detail || d.__httperr));
}
function errMsg(d){
  if (!d) return '无数据';
  return d.error || d.detail || (d.__httperr ? '服务不可达或降级（HTTP '+(d.status||'?')+'）' : '数据异常');
}
const DATA_STATUS_CN = { fresh:'实时', delayed:'延迟', stale:'过期', error:'错误', fallback:'回退源' };
function verdictClass(v){ return v==='偏多' ? 'v-long' : v==='偏空' ? 'v-short' : 'v-flat'; }
function dirOf(chg){ return chg==null||isNaN(chg) ? 'flat' : chg>0 ? 'up' : chg<0 ? 'down' : 'flat'; }
function arrowOf(chg){ return chg==null||isNaN(chg) ? '·' : chg>0 ? '▲' : chg<0 ? '▼' : '—'; }

/* ---------------- board universe (A股分行业) ---------------- */
const SECTORS = [
  {name:'白酒消费', syms:[['600519','贵州茅台'],['000858','五粮液'],['000568','泸州老窖'],['600809','山西汾酒'],['002304','洋河股份']]},
  {name:'银行',     syms:[['601398','工商银行'],['600036','招商银行'],['601288','农业银行'],['601166','兴业银行'],['600000','浦发银行']]},
  {name:'非银金融', syms:[['601318','中国平安'],['600030','中信证券'],['300059','东方财富'],['601628','中国人寿']]},
  {name:'医药生物', syms:[['600276','恒瑞医药'],['300760','迈瑞医疗'],['603259','药明康德'],['000538','云南白药']]},
  {name:'新能源',   syms:[['300750','宁德时代'],['002594','比亚迪'],['601012','隆基绿能'],['002460','赣锋锂业']]},
  {name:'科技半导体', syms:[['002415','海康威视'],['000725','京东方A'],['688981','中芯国际'],['002230','科大讯飞'],['603501','韦尔股份']]},
  {name:'家电食品', syms:[['000333','美的集团'],['000651','格力电器'],['600887','伊利股份'],['603288','海天味业']]},
  {name:'资源能源', syms:[['601857','中国石油'],['600028','中国石化'],['601088','中国神华'],['600019','宝钢股份']]},
  {name:'地产基建', syms:[['000002','万科A'],['600048','保利发展'],['601668','中国建筑']]},
];
const INDICES = [['sh000001','上证指数'],['sz399001','深证成指'],['sz399006','创业板指'],
                 ['sh000300','沪深300'],['sh000905','中证500'],['sh000688','科创50']];

function allBoardSymbols(){
  const out = INDICES.map(x => 'ASHARE:'+x[0]);
  SECTORS.forEach(s => s.syms.forEach(t => out.push('ASHARE:'+t[0])));
  return out;
}

/* ---------------- state ---------------- */
let MODE = 'quick';
let chartMain = null, chartOsc = null, btChart = null;
const hasECharts = (typeof echarts !== 'undefined');
let boardTimer = null, clockTimer = null;
let lastPrices = {};        // symbol -> 上轮价格（用于变价闪烁）
let lastUpdated = 0;        // 盯盘墙最近成功刷新时刻 (Date.now)
let boardFirst = true;      // 首屏不闪烁

/* ============================================================
   北京时段 / 时钟
   ============================================================ */
function beijingParts(){
  const f = new Intl.DateTimeFormat('en-US',{timeZone:'Asia/Shanghai',hour12:false,
    weekday:'short',hour:'2-digit',minute:'2-digit',second:'2-digit'});
  const p = {}; f.formatToParts(new Date()).forEach(x => p[x.type]=x.value);
  return p;
}
function marketSession(){
  const p = beijingParts();
  const h = parseInt(p.hour,10)%24, m = parseInt(p.minute,10), t = h*60+m;
  if (p.weekday==='Sat' || p.weekday==='Sun') return {cls:'closed', txt:'周末休市'};
  if (t>=555 && t<570)  return {cls:'lunch',  txt:'集合竞价'};   // 09:15–09:30
  if ((t>=570 && t<690) || (t>=780 && t<900)) return {cls:'open', txt:'交易中'}; // 09:30–11:30 / 13:00–15:00
  if (t>=690 && t<780)  return {cls:'lunch',  txt:'午间休市'};   // 11:30–13:00
  if (t<555)            return {cls:'closed', txt:'盘前'};
  return {cls:'closed', txt:'已收盘'};
}
function tickClock(){
  const p = beijingParts();
  const wdCN = {Mon:'周一',Tue:'周二',Wed:'周三',Thu:'周四',Fri:'周五',Sat:'周六',Sun:'周日'}[p.weekday]||'';
  $('clock').innerHTML = '北京 '+wdCN+' <b>'+p.hour+':'+p.minute+':'+p.second+'</b>';
  const s = marketSession();
  const el = $('session'); el.className = 'session '+s.cls; el.textContent = s.txt;
  // 更新"X秒前"
  const ago = $('liveAgo');
  if (ago && lastUpdated){
    const sec = Math.round((Date.now()-lastUpdated)/1000);
    ago.textContent = sec<2 ? '刚刚更新' : ('更新于 '+sec+'s 前');
  }
}

/* ============================================================
   VIEW 切换
   ============================================================ */
function showBoard(){
  stopBoardPoll();
  $('detailView').classList.add('hidden');
  $('boardView').classList.remove('hidden');
  $('pulsebar').classList.remove('hidden');
  window.scrollTo({top:0, behavior:'instant'});
  loadBoard();
  startBoardPoll();
}
function openDetail(sym){
  stopBoardPoll();
  $('boardView').classList.add('hidden');
  $('pulsebar').classList.add('hidden');
  $('detailView').classList.remove('hidden');
  $('symbol').value = sym;
  setMode('quick');
  window.scrollTo({top:0, behavior:'instant'});
  run();
}
function setMode(m){
  MODE = m;
  document.querySelectorAll('.modebtn[data-mode]').forEach(b =>
    b.classList.toggle('active', b.dataset.mode===m));
}

/* ============================================================
   BOARD · 批量行情 → 脉搏 + 涨跌家数 + 分行业墙
   ============================================================ */
async function loadBoard(){
  const syms = allBoardSymbols();
  const data = await getJSON('/api/finance/board?symbols=' + encodeURIComponent(syms.join(',')));
  if (isErr(data) || !Array.isArray(data)){
    $('boardBody').innerHTML = '<div class="notice err">盯盘墙行情不可用：'+esc(errMsg(data))
      + ' — 行情源可能不可达或被限流。</div>';
    return;
  }
  const map = {};
  data.forEach(q => { if (q && q.symbol) map[q.symbol] = q; });
  renderPulse(map);
  renderBreadth(map);
  renderSectors(map);
  lastUpdated = Date.now();
  boardFirst = false;
  tickClock();
}

function renderPulse(map){
  const row = $('idxRow');
  row.innerHTML = INDICES.map(([code,nm]) => {
    const q = map['ASHARE:'+code] || {};
    const chg = q.change_pct;
    const d = dirOf(chg);
    return '<div class="idx-chip"><span class="nm">'+esc(nm)+'</span>'
      + '<span class="px '+d+'">'+fmt(q.price, 2)+'</span>'
      + '<span class="pc '+d+'">'+arrowOf(chg)+' '+(chg==null?'—':signed(chg)+'%')+'</span></div>';
  }).join('');
}

function renderBreadth(map){
  let up=0, down=0, flat=0, sum=0, n=0;
  SECTORS.forEach(s => s.syms.forEach(([code]) => {
    const q = map['ASHARE:'+code]; if (!q || q.error) return;
    const c = q.change_pct;
    if (c==null) { flat++; return; }
    if (c>0) up++; else if (c<0) down++; else flat++;
    sum += c; n++;
  }));
  const avg = n ? sum/n : null;
  const ad = dirOf(avg);
  $('breadth').innerHTML =
      '<div class="grp"><span class="n up">'+up+'</span><span class="l">涨</span></div>'
    + '<div class="grp"><span class="n flat">'+flat+'</span><span class="l">平</span></div>'
    + '<div class="grp"><span class="n down">'+down+'</span><span class="l">跌</span></div>'
    + '<div class="grp"><span class="n '+ad+'">'+(avg==null?'—':signed(avg)+'%')+'</span><span class="l">均涨幅</span></div>';
}

function renderSectors(map){
  let html = '';
  SECTORS.forEach(sec => {
    let sum=0, n=0;
    const cells = sec.syms.map(([code,nm]) => {
      const sym = 'ASHARE:'+code, q = map[sym];
      if (q && !q.error && q.change_pct!=null){ sum+=q.change_pct; n++; }
      return ticker(sym, code, nm, q);
    }).join('');
    const avg = n ? sum/n : null, ad = dirOf(avg);
    const avgTxt = avg==null ? '—' : signed(avg)+'%';
    const avgColor = ad==='up' ? 'var(--up)' : ad==='down' ? 'var(--down)' : 'var(--ink-soft)';
    html += '<div class="sector"><div class="sec-head"><span class="nm">'+esc(sec.name)+'</span>'
      + '<span class="bar"></span><span class="avg" style="color:'+avgColor+'">行业 '+avgTxt+'</span></div>'
      + '<div class="tickers">'+cells+'</div></div>';
  });
  $('boardBody').innerHTML = html;
}

function ticker(sym, code, nm, q){
  if (!q || q.error || q.price==null){
    return '<div class="ticker dead"><div class="tname"><span class="nm">'+esc(nm)+'</span>'
      + '<span class="cd">'+esc(code)+'</span></div><div class="tpx">—</div>'
      + '<div class="trow"><span class="tchg">无行情</span><span class="tflag">降级</span></div></div>';
  }
  const chg = q.change_pct, d = dirOf(chg);
  // 变价闪烁（非首屏）
  let flash = '';
  const prev = lastPrices[sym];
  if (!boardFirst && prev!=null && q.price!=null && q.price!==prev){
    flash = q.price>prev ? ' fl-up' : ' fl-down';
  }
  lastPrices[sym] = q.price;
  const st = q.data_status || 'fresh';
  let flag = DATA_STATUS_CN[st]||st;
  if (q.halted) flag = '停牌';
  else if (q.limit_up) flag = '涨停';
  else if (q.limit_down) flag = '跌停';
  return '<div class="ticker '+d+flash+'" data-sym="'+esc(sym)+'" role="button" tabindex="0">'
    + '<div class="tname"><span class="nm">'+esc(q.name||nm)+'</span><span class="cd">'+esc(code)+'</span></div>'
    + '<div class="tpx">'+fmt(q.price,2)+'</div>'
    + '<div class="trow"><span class="tchg">'+arrowOf(chg)+' '+(chg==null?'—':signed(chg)+'%')+'</span>'
    + '<span class="tflag">'+esc(flag)+'</span></div></div>';
}

function startBoardPoll(){
  stopBoardPoll();
  boardTimer = setInterval(() => { if (!document.hidden) loadBoard(); }, 12000);
  setLive(true);
}
function stopBoardPoll(){ if (boardTimer){ clearInterval(boardTimer); boardTimer=null; } setLive(false); }
function setLive(on){
  const el = $('liveWrap'); if (!el) return;
  el.classList.toggle('paused', !on);
  const lbl = $('liveLbl'); if (lbl) lbl.textContent = on ? 'LIVE · 12s' : '已暂停';
}

/* ============================================================
   DETAIL · 个股研判（quick/deep/review/quant/teach）
   ============================================================ */
function curSymbol(){ return ($('symbol').value || '').trim() || 'ASHARE:600519'; }

async function run(){
  const sym = curSymbol();
  const noChart = (MODE === 'teach' || MODE === 'review' || MODE === 'quant');
  $('chartSec').style.display  = noChart ? 'none' : '';
  $('newsSec').style.display   = noChart ? 'none' : '';
  $('quotebar').style.display  = noChart ? 'none' : '';

  const A = $('analysis');
  A.innerHTML = '<section><div class="card"><div class="loading"><i></i><i></i><i></i> '
    + ({quick:'快速体检中…', deep:'委员会研判中（4 位分析师 + ML 票 → 治理引擎 → 主席汇总，约需 10–60s）…',
        review:'读取自审计记录…', teach:'载入教学内容…'}[MODE] || '处理中…') + '</div></section>';
  try {
    if (MODE === 'teach')  return renderTeach(await getJSON('/api/finance/analyze', postBody(sym,'teach')));
    if (MODE === 'review') return renderReview(await getJSON('/api/finance/analyze', postBody(sym,'review')));
    if (MODE === 'quant')  return renderQuant();
    // quick/deep：图表(K线)单独取；报价+新闻复用 analyze 响应（同一 MCP 会话已取，省并发外部调用）
    loadCharts(sym);
    $('quotebar').style.display = '';
    $('quotebar').innerHTML = '<div class="loading"><i></i><i></i><i></i> 行情加载中…</div>';
    $('newsBox').innerHTML = '<div class="loading"><i></i><i></i><i></i> 新闻加载中…</div>';
    const data = await getJSON('/api/finance/analyze', postBody(sym, MODE));
    if (isErr(data)) { A.innerHTML = sectionNotice('研判失败', errMsg(data), true);
      $('quotebar').innerHTML = '<div class="notice err" style="width:100%">行情不可用：'+esc(errMsg(data))+'</div>'; return; }
    if (data.quote != null) renderQuoteData(data.quote, sym); else loadQuote(sym);
    if (data.news != null)  renderNewsInto($('newsBox'), data.news); else loadNews(sym);
    if (MODE === 'quick') renderQuick(data); else renderDeep(data);
  } catch(e){ A.innerHTML = sectionNotice('请求异常', String(e), true); }
}
function postBody(symbol, mode){
  return { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ symbol, mode }) };
}
function sectionNotice(title, msg, isError){
  return '<section><div class="sec-title">'+esc(title)+'</div>'
    + '<div class="card"><div class="notice'+(isError?' err':'')+'">'+esc(msg)+'</div></div></section>';
}

/* ---- QUOTE strip ---- */
async function loadQuote(sym){
  const bar = $('quotebar'); bar.style.display = '';
  bar.innerHTML = '<div class="loading"><i></i><i></i><i></i> 行情加载中…</div>';
  renderQuoteData(await getJSON('/api/finance/quote?symbol=' + encodeURIComponent(sym)), sym);
}
function renderQuoteData(q, sym){
  const bar = $('quotebar'); bar.style.display = '';
  if (isErr(q)){
    bar.innerHTML = '<div class="notice err" style="width:100%">行情不可用：'+esc(errMsg(q))
      + ' — 该市场可能不可达或被限流，已降级。</div>';
    return;
  }
  const chg = q.change_pct, dir = dirOf(chg), arrow = arrowOf(chg);
  const st = q.data_status || 'fresh';
  let badges = '<span class="badge '+esc(st)+'">'+ (DATA_STATUS_CN[st]||st) +'</span>';
  if (q.halted)     badges += ' <span class="badge halt">停牌</span>';
  if (q.limit_up)   badges += ' <span class="badge lu">涨停</span>';
  if (q.limit_down) badges += ' <span class="badge ld">跌停</span>';
  if (q.source)     badges += ' <span class="badge tag">源 '+esc(q.source)+'</span>';
  bar.innerHTML =
      '<div><div class="qname">'+esc(q.name||sym)+'</div><div class="qsym">'+esc(sym)+'</div></div>'
    + '<div class="qprice '+dir+'">'+ fmt(q.price) +'</div>'
    + '<div class="qchg '+dir+'">'+arrow+' '+ (chg==null?'—':signed(chg)+'%') +'</div>'
    + '<div class="qmeta">昨收 '+fmt(q.prev_close)+' &nbsp;'+badges+'</div>';
}

/* ---- CHARTS ---- */
function sma(arr, n){
  const out = new Array(arr.length).fill(null); let sum = 0;
  for (let i=0;i<arr.length;i++){ sum += arr[i]; if (i>=n) sum -= arr[i-n]; if (i>=n-1) out[i] = +(sum/n).toFixed(4); }
  return out;
}
function ema(arr, n){
  const out = new Array(arr.length).fill(null); const k = 2/(n+1); let prev = null;
  for (let i=0;i<arr.length;i++){ prev = prev==null ? arr[i] : arr[i]*k + prev*(1-k); out[i] = +prev.toFixed(4); }
  return out;
}
function macdSeries(closes){
  const ef = ema(closes,12), es = ema(closes,26);
  const dif = closes.map((_,i)=> +(ef[i]-es[i]).toFixed(4));
  const dea = ema(dif,9);
  const hist = dif.map((_,i)=> +((dif[i]-dea[i])*2).toFixed(4));
  return {dif, dea, hist};
}
function rsiSeries(closes, n){
  n = n||14; const out = new Array(closes.length).fill(null); let gain=0, loss=0;
  for (let i=1;i<closes.length;i++){
    const d = closes[i]-closes[i-1]; const g = d>0?d:0, l = d<0?-d:0;
    if (i<=n){ gain+=g; loss+=l; if (i===n){ gain/=n; loss/=n; out[i]= loss===0?100:+(100-100/(1+gain/loss)).toFixed(2); } }
    else { gain=(gain*(n-1)+g)/n; loss=(loss*(n-1)+l)/n; out[i]= loss===0?100:+(100-100/(1+gain/loss)).toFixed(2); }
  }
  return out;
}
async function loadCharts(sym){
  if (!hasECharts){ $('chartNote').innerHTML = '<span style="color:var(--danger)">ECharts 未加载 — 图表降级。</span>'; return; }
  if (!chartMain) chartMain = echarts.init($('chart-main'), null, { renderer:'canvas' });
  if (!chartOsc)  chartOsc  = echarts.init($('chart-osc'),  null, { renderer:'canvas' });
  chartMain.showLoading({ text:'载入 K 线…', textColor:'#9fb2a6', maskColor:'rgba(8,11,10,.6)', color:'#3fcf8e' });
  chartOsc.clear();
  const kl = await getJSON('/api/finance/kline?symbol=' + encodeURIComponent(sym) + '&count=120');
  chartMain.hideLoading();
  if (isErr(kl) || !Array.isArray(kl) || !kl.length){
    chartMain.clear();
    chartMain.setOption(emptyChartOption(isErr(kl) ? ('K线不可用：'+errMsg(kl)) : '该标的暂无 K 线数据（市场不可达/降级）'));
    return;
  }
  const dates  = kl.map(d => String(d.ts));
  const ohlc   = kl.map(d => [d.open, d.close, d.low, d.high]);
  const closes = kl.map(d => d.close);
  const vols   = kl.map(d => ({ value: d.volume==null?0:d.volume,
                       itemStyle: { color: d.close >= d.open ? 'rgba(255,77,82,.55)' : 'rgba(22,199,132,.5)' } }));
  const ma5 = sma(closes,5), ma20 = sma(closes,20);
  const mac = macdSeries(closes), rsi = rsiSeries(closes,14);
  const axisLine = { lineStyle:{ color:'#243029' } };
  const splitLine = { lineStyle:{ color:'rgba(36,48,41,.5)' } };
  const txt = { color:'#687a70', fontFamily:'Consolas, monospace', fontSize:10 };
  chartMain.setOption({
    backgroundColor:'transparent', animation:true,
    tooltip:{ trigger:'axis', axisPointer:{ type:'cross' }, backgroundColor:'#0a100d',
      borderColor:'#243029', textStyle:{ color:'#eef5f0', fontFamily:'Consolas, monospace', fontSize:11 } },
    legend:{ data:['K线','MA5','MA20','成交量'], textStyle:{ color:'#9fb2a6', fontSize:11 }, top:0, right:10 },
    grid:[ { left:54, right:18, top:34, height:'58%' }, { left:54, right:18, top:'72%', height:'18%' } ],
    axisPointer:{ link:[{ xAxisIndex:'all' }] },
    xAxis:[
      { type:'category', data:dates, gridIndex:0, axisLine, axisLabel:txt, splitLine:{show:false}, boundaryGap:true },
      { type:'category', data:dates, gridIndex:1, axisLine, axisLabel:{show:false}, axisTick:{show:false} }
    ],
    yAxis:[
      { scale:true, gridIndex:0, axisLine, axisLabel:txt, splitLine },
      { scale:true, gridIndex:1, axisLine, axisLabel:{show:false}, splitLine:{show:false} }
    ],
    dataZoom:[
      { type:'inside', xAxisIndex:[0,1], start:55, end:100 },
      { type:'slider', xAxisIndex:[0,1], start:55, end:100, bottom:2, height:14,
        borderColor:'#243029', fillerColor:'rgba(63,207,142,.12)', textStyle:{ color:'#687a70', fontSize:9 },
        handleStyle:{ color:'#1f8f63' }, dataBackground:{ lineStyle:{color:'#243029'}, areaStyle:{color:'#121a17'} } }
    ],
    series:[
      { name:'K线', type:'candlestick', data:ohlc, xAxisIndex:0, yAxisIndex:0,
        itemStyle:{ color:'#ff4d52', color0:'#16c784', borderColor:'#ff4d52', borderColor0:'#16c784' } },
      { name:'MA5', type:'line', data:ma5, xAxisIndex:0, yAxisIndex:0, smooth:true, symbol:'none', lineStyle:{ width:1.3, color:'#e7bd5e' } },
      { name:'MA20', type:'line', data:ma20, xAxisIndex:0, yAxisIndex:0, smooth:true, symbol:'none', lineStyle:{ width:1.3, color:'#5fa8e2' } },
      { name:'成交量', type:'bar', data:vols, xAxisIndex:1, yAxisIndex:1 }
    ]
  }, true);
  chartOsc.setOption({
    backgroundColor:'transparent',
    tooltip:{ trigger:'axis', backgroundColor:'#0a100d', borderColor:'#243029',
      textStyle:{ color:'#eef5f0', fontFamily:'Consolas, monospace', fontSize:11 } },
    legend:{ data:['MACD','DIF','DEA','RSI14'], textStyle:{ color:'#9fb2a6', fontSize:10 }, top:0, right:10 },
    grid:{ left:54, right:48, top:24, bottom:18 },
    xAxis:{ type:'category', data:dates, axisLine, axisLabel:txt },
    yAxis:[
      { scale:true, axisLine, axisLabel:txt, splitLine },
      { scale:true, min:0, max:100, position:'right', axisLine, axisLabel:{ ...txt, formatter:'{value}' },
        splitLine:{show:false}, name:'RSI', nameTextStyle:{ color:'#687a70', fontSize:9 } }
    ],
    dataZoom:[ { type:'inside', start:55, end:100 } ],
    series:[
      { name:'MACD', type:'bar', data: mac.hist.map(v => ({ value:v,
          itemStyle:{ color: v>=0 ? 'rgba(255,77,82,.7)' : 'rgba(22,199,132,.6)' } })) },
      { name:'DIF', type:'line', data:mac.dif, symbol:'none', lineStyle:{ width:1, color:'#e7bd5e' } },
      { name:'DEA', type:'line', data:mac.dea, symbol:'none', lineStyle:{ width:1, color:'#5fa8e2' } },
      { name:'RSI14', type:'line', yAxisIndex:1, data:rsi, symbol:'none', lineStyle:{ width:1.2, color:'#3fcf8e' },
        markLine:{ silent:true, symbol:'none', label:{ color:'#687a70', fontSize:9 },
          lineStyle:{ color:'#243029', type:'dashed' }, data:[{ yAxis:70 },{ yAxis:30 }] } }
    ]
  }, true);
  $('chartNote').innerHTML = 'MA5（黄）/ MA20（蓝）叠加 · 量能（涨红跌绿）· 副图 MACD 柱 + DIF/DEA + RSI14。'
    + ' 共 ' + kl.length + ' 根 K 线 · 指标据收盘价本地滚动计算。';
}
function emptyChartOption(msg){
  return { backgroundColor:'transparent',
    title:{ text: msg, left:'center', top:'middle',
      textStyle:{ color:'#687a70', fontFamily:'Consolas, monospace', fontSize:13, fontWeight:'normal' } } };
}
window.addEventListener('resize', () => { if (chartMain) chartMain.resize(); if (chartOsc) chartOsc.resize(); });

/* ---- NEWS ---- */
async function loadNews(sym){
  const box = $('newsBox');
  box.innerHTML = '<div class="loading"><i></i><i></i><i></i> 新闻加载中…</div>';
  renderNewsInto(box, await getJSON('/api/finance/news?symbol=' + encodeURIComponent(sym) + '&limit=8'));
}
function renderNewsInto(box, news){
  if (isErr(news)){ box.innerHTML = '<div class="notice err">新闻不可用：'+esc(errMsg(news))+'</div>'; return; }
  if (!Array.isArray(news) || !news.length){
    box.innerHTML = '<div class="empty-soft">暂无相关新闻（该市场新闻源可能不稳定或返回为空）。</div>'; return;
  }
  box.innerHTML = news.map(n => {
    const t = esc(n.title || '(无标题)');
    const su = safeUrl(n.url);
    const a = su ? '<a href="'+esc(su)+'" target="_blank" rel="noopener">'+t+' ↗</a>' : '<span class="news-title">'+t+'</span>';
    const meta = esc([n.source, n.ts].filter(Boolean).join(' · '));
    return '<div class="news-item">'+a+'<span class="meta">'+meta+'</span></div>';
  }).join('');
}

/* ---- QUICK ---- */
function renderQuick(data){
  const A = $('analysis');
  const sig = data.signals || {};
  const sigs = Array.isArray(sig.signals) ? sig.signals : [];
  const ind = sig.indicators || {};
  let html = '<section><div class="sec-title">Quick · 快速体检 <span class="cn">规则信号</span></div><div class="card">';
  if (!sigs.length){ html += '<div class="empty-soft">'+esc(sig.text || '无显著信号')+'</div>'; }
  else { html += '<div class="sig-list">' + sigs.map(s => '<span class="sig">'+esc(s)+'</span>').join('') + '</div>'; }
  const cells = [
    ['MA5', fmt(ind.ma5)], ['MA10', fmt(ind.ma10)], ['MA20', fmt(ind.ma20)], ['MA60', fmt(ind.ma60)],
    ['RSI14', fmt(ind.rsi14,1)], ['MACD柱', fmt((ind.macd||{}).hist,3)],
    ['量比', ind.vol_ratio==null?'—':fmt(ind.vol_ratio,2)], ['BOLL中轨', fmt((ind.boll||{}).mid)]
  ];
  html += '<div class="ind-grid">' + cells.map(c =>
    '<div class="cell"><div class="k">'+esc(c[0])+'</div><div class="v">'+esc(c[1])+'</div></div>').join('') + '</div>';
  html += '</div></section>';
  A.innerHTML = html;
  if (data.disclaimer) $('footDisc').textContent = data.disclaimer;
}

/* ---- DEEP ---- */
function renderDeep(data){
  const A = $('analysis');
  const members = Array.isArray(data.members) ? data.members : [];
  const chair = data.chairman || {};
  const gov = Array.isArray(data.governance_report) ? data.governance_report : [];
  const ml = data.ml || {};
  const ds = data.data_status || 'fresh';
  const conf = (data.confidence != null) ? data.confidence : (chair.confidence != null ? chair.confidence : 0);
  let html = '';
  if (data.conflict){
    const di = (typeof data.disagreement === 'number') ? data.disagreement : null;
    html += '<section><div class="notice"><b>⚠ 委员意见冲突</b> — 存在偏多/偏空对立，治理引擎按<b>分歧指数'
      + (di != null ? ' ' + di : '') + '</b>（0=一致，1=势均力敌）梯度压低置信度天花板并强制暴露分歧。</div></section>';
  }
  // 智能体自主取证（LLM 自主调用 MCP 实时工具）—— MCP 活性可视化
  if (data.agentic && data.agentic.research){
    const tr = Array.isArray(data.agentic.trace) ? data.agentic.trace : [];
    html += '<section><div class="sec-title">Agentic · 智能体自主取证 <span class="cn">LLM 自主调用 MCP 工具</span></div><div class="card">';
    if (tr.length){
      html += '<div class="ev-title">本轮 LLM 自主调用的实时工具（offline 工具被 §3.4 硬隔离）</div>'
        + '<div class="chips-sm">' + tr.map(t =>
            '<span class="'+(t.blocked?'chip-counter':'chip-risk')+'">'+esc(t.tool)+(t.blocked?' ⛔offline':'')+'</span>').join('') + '</div>';
    }
    html += '<div class="review-note" style="white-space:pre-wrap;margin-top:12px">'+esc(data.agentic.research)+'</div>';
    html += '</div></section>';
  }
  html += '<section><div class="sec-title">Committee · 委员会研判 <span class="cn">证据链投研委员会</span></div><div class="grid mem">';
  members.forEach(m => { html += memberCard(m); });
  if (!members.length) html += '<div class="empty-soft">无委员意见。</div>';
  html += '</div></section>';
  html += '<section><div class="sec-title">Chairman · 主席结论 <span class="cn">汇总 · 置信度环</span></div><div class="card"><div class="chair-grid">';
  html += confRing(conf, data.verdict || chair.final || '中性');
  html += '<div class="chair-detail"><dl>'+ dlRow('多数意见', chair.majority) + dlRow('少数意见', chair.minority)
    + dlRow('分歧来源', chair.disagreement) + '</dl></div></div></div></section>';
  html += '<section><div class="sec-title">Decision · 反证驱动决策解释 <span class="cn">Counter-evidence-aware</span></div>';
  html += '<div class="ce-panel"><div class="ce-grid">';
  html += ceBlock('support', '主要支持证据', 'KEY EVIDENCE', chair.key_evidence);
  html += ceBlock('against', '主要反对证据', 'COUNTER EVIDENCE', chair.counter_evidence);
  html += ceBlock('invalid', '结论失效条件', 'INVALIDATION', chair.invalidation);
  html += ceBlock('dissent', '异议委员', 'DISSENT', chair.dissent);
  html += ceBlock('risk', '最大风险', 'MAX RISK', chair.max_risk);
  html += ceBlock('reason', '置信度解释', 'CONFIDENCE REASON', chair.confidence_reason);
  html += '<div class="ce-block full"><div class="k"><span class="cn">治理记录</span> GOVERNANCE REPORT · R1–R13</div>'
    + '<div class="govlog">' + (gov.length
        ? gov.map((g,i) => '<div class="ln"><span class="idx">'+String(i+1).padStart(2,'0')+'</span><span class="rule">'+esc(g)+'</span></div>').join('')
        : '<div class="empty">无规则触发 — 证据充分、数据新鲜、无冲突。置信度天花板维持默认 0.85。</div>')
    + '</div><div style="margin-top:12px;display:flex;gap:10px;align-items:center;flex-wrap:wrap">'
    + '<span class="badge '+esc(ds)+'">数据 '+ (DATA_STATUS_CN[ds]||ds) +'</span>'
    + '<span style="font-family:var(--mono);font-size:11px;color:var(--ink-faint)">'+esc(data.disclaimer || '仅供学习研究，不构成投资建议。')+'</span>'
    + '</div></div></div></div></section>';
  html += '<section><div class="sec-title">ML · XGBoost 风险信号 <span class="cn">次日波动预测（校准不确定性）</span></div><div class="card"><div class="ml-ticket">';
  const pbm = ml.prob_big_move; const abst = ml.abstain || pbm == null;
  const lvl = pbm == null ? '' : (pbm > 0.6 ? '高' : (pbm > 0.4 ? '中' : '低'));
  html += '<div class="stub"><div class="k">次日大波动概率</div><div class="v'+(abst?' abst':'')+'">'
    + (abst ? '弃权' : (pct(pbm) + (lvl ? ' · '+lvl+'风险' : ''))) + '</div></div>';
  html += '<div class="stub"><div class="k">样本外 AUC</div><div class="v'+(ml.auc==null?' abst':'')+'">'
    + (ml.auc==null?'—':fmt(ml.auc,3)) + '</div></div>';
  html += '<div class="note">'
    + (abst ? ('该票<b style="color:var(--amber)"> 已弃权</b>'+ (ml.abstain_reason ? '：'+esc(ml.abstain_reason) : '（AUC≈0.5 或样本不足）') + '。治理规则 R4 会将其剔除。')
            : '模型预测<b>次日是否为大波动日</b>（波动具聚集性、可学习），用于<b>校准不确定性</b>而非指示方向；高波动 → 治理规则 R7 下调整体置信度。')
    + '</div></div></div></section>';
  const bt = data.backtest;
  const hasBt = bt && Array.isArray(bt.equity_curve) && bt.equity_curve.length >= 2 && !bt.error;
  if (hasBt){
    const s = bt.significance || {};
    const sigTxt = s.significant === true ? ('显著 (p='+s.p_value+')')
                 : s.significant === false ? ('不显著 (p='+s.p_value+'，恐为运气)') : '样本不足';
    html += '<section><div class="sec-title">Backtest · 可信回测 <span class="cn">双均线净值 vs 买入持有 · 块自助显著性</span></div>'
      + '<div class="card"><div class="review-stats">'
      + '<div class="stat"><div class="k">策略收益</div><div class="v">'+pct(bt.total_return)+'</div></div>'
      + '<div class="stat"><div class="k">买入持有</div><div class="v">'+pct(bt.benchmark_return)+'</div></div>'
      + '<div class="stat"><div class="k">最大回撤</div><div class="v">'+pct(bt.max_drawdown)+'</div></div>'
      + '<div class="stat"><div class="k">夏普</div><div class="v">'+fmt(bt.sharpe,2)+'</div></div>'
      + '<div class="stat"><div class="k">边际显著性</div><div class="v'+(s.significant===false?' warn':'')+'">'+esc(sigTxt)+'</div></div>'
      + '</div><div id="bt-chart" style="height:240px;margin-top:12px"></div>'
      + '<div class="chart-note">'+esc(bt.disclaimer||'')+'</div></div></section>';
  }
  A.innerHTML = html;
  if (hasBt){
    try {
      if (btChart){ btChart.dispose(); btChart = null; }
      btChart = echarts.init($('bt-chart'), null, { renderer:'canvas' });
      const eq = bt.equity_curve, bench = bt.benchmark_curve || [];
      btChart.setOption({
        grid:{ left:46, right:16, top:26, bottom:22 }, tooltip:{ trigger:'axis' },
        legend:{ data:['策略净值','买入持有'], top:0, textStyle:{ fontSize:11, color:'#9fb2a6' } },
        xAxis:{ type:'category', data:eq.map((_,i)=>i), axisLabel:{ show:false } },
        yAxis:{ type:'value', scale:true, axisLabel:{ color:'#687a70' } },
        series:[
          { name:'策略净值', type:'line', data:eq, smooth:true, showSymbol:false, lineStyle:{ width:2, color:'#3fcf8e' } },
          { name:'买入持有', type:'line', data:bench, smooth:true, showSymbol:false, lineStyle:{ width:1, type:'dashed', color:'#5fa8e2' } }
        ]
      });
    } catch(e){ /* 图表失败不影响其余面板 */ }
  }
  if (data.disclaimer) $('footDisc').textContent = data.disclaimer;
}

function memberCard(m){
  const ab = !!m.abstain;
  const v = m.verdict || '中性';
  const vc = ab ? 'v-abst' : verdictClass(v);
  const vlabel = ab ? '弃权' : v;
  const c = Math.max(0, Math.min(1, Number(m.confidence)||0));
  let html = '<div class="member"><div class="head"><span class="lens">'+esc(m.lens||'委员')+'</span>'
    + '<span class="verdict '+vc+'">'+esc(vlabel)+'</span></div>';
  if (ab){ html += '<div class="abstain-box">⊘ 已弃权：'+esc(m.abstain_reason || '数据/证据不足，按治理要求拒绝给出强结论')+'</div>'; }
  html += '<div class="conf"><div class="meta"><span>CONFIDENCE</span><span>'+pct(c)+'</span></div>'
    + '<div class="track"><div class="fill" style="width:'+(c*100).toFixed(0)+'%"></div></div></div>';
  const reasons = Array.isArray(m.reasons) ? m.reasons.filter(Boolean) : [];
  if (reasons.length){ html += '<ul class="reasons">' + reasons.map(r => '<li>'+esc(r)+'</li>').join('') + '</ul>'; }
  const ev = Array.isArray(m.evidence) ? m.evidence : [];
  if (ev.length){ html += '<div class="ev-title">证据 · Evidence</div>' + ev.map(e => evidenceLine(e, false)).join(''); }
  const ce = Array.isArray(m.counter_evidence) ? m.counter_evidence.filter(Boolean) : [];
  if (ce.length){
    html += '<div class="chips-sm">' + ce.map(x =>
      '<span class="chip-counter">反证 · '+esc(typeof x==='string'?x:(x.value||JSON.stringify(x)))+'</span>').join('') + '</div>';
  }
  const risks = Array.isArray(m.risks) ? m.risks.filter(Boolean) : [];
  if (risks.length){ html += '<div class="chips-sm">' + risks.map(r => '<span class="chip-risk">风险 · '+esc(r)+'</span>').join('') + '</div>'; }
  html += '</div>';
  return html;
}
function evidenceLine(e, counter){
  if (e == null) return '';
  if (typeof e === 'string'){ return '<div class="ev'+(counter?' counter':'')+'"><div class="row eval">'+esc(e)+'</div></div>'; }
  const type = e.type || '?', src = e.source || '';
  const val = e.value == null ? '' : (typeof e.value === 'object' ? JSON.stringify(e.value) : e.value);
  const intp = e.interpretation || '';
  return '<div class="ev'+(counter?' counter':'')+'"><div class="row">'
    + '<span class="etype">['+esc(type)+']</span> '
    + (src ? '<span class="esrc">'+esc(src)+'</span>: ' : '')
    + '<span class="eval">'+esc(val)+'</span>'
    + (intp ? ' <span class="eint">— '+esc(intp)+'</span>' : '') + '</div></div>';
}
function confRing(conf, verdict){
  const c = Math.max(0, Math.min(1, Number(conf)||0));
  const R = 64, C = 2*Math.PI*R, off = C * (1 - c);
  const ringColor = verdict==='偏多' ? '#ff4d52' : verdict==='偏空' ? '#16c784' : '#5fa8e2';
  const vClass = verdict==='偏多' ? 'up' : verdict==='偏空' ? 'down' : 'flat';
  return '<div class="ring-wrap"><div class="ring"><svg width="160" height="160" viewBox="0 0 160 160">'
    + '<circle cx="80" cy="80" r="'+R+'" fill="none" stroke="#243029" stroke-width="11"></circle>'
    + '<circle cx="80" cy="80" r="'+R+'" fill="none" stroke="'+ringColor+'" stroke-width="11" stroke-linecap="round"'
    + ' stroke-dasharray="'+C.toFixed(1)+'" stroke-dashoffset="'+off.toFixed(1)+'" style="transition:stroke-dashoffset .8s ease"></circle></svg>'
    + '<div class="ctr"><div class="pct" style="color:'+ringColor+'">'+(c*100).toFixed(0)+'%</div><div class="lbl">Confidence</div></div></div>'
    + '<div class="ring-verdict '+vClass+'">'+esc(verdict)+'</div></div>';
}
function ceBlock(kind, cn, en, val){
  const has = val != null && String(val).trim() !== '';
  return '<div class="ce-block '+kind+'"><div class="k"><span class="cn">'+esc(cn)+'</span> '+esc(en)+'</div>'
    + '<div class="v">'+ (has ? esc(val) : '<span style="color:var(--ink-faint)">—（主席未提供 / 不适用）</span>') +'</div></div>';
}
function dlRow(k, v){
  return '<dt>'+esc(k)+'</dt><dd>'+ (v!=null && String(v).trim() ? esc(v) : '<span style="color:var(--ink-faint)">—</span>') +'</dd>';
}

/* ---- REVIEW ---- */
function renderReview(data){
  const A = $('analysis');
  if (isErr(data)){ A.innerHTML = sectionNotice('复盘失败', errMsg(data), true); return; }
  const r = data.review || {};
  const reviewed = r.reviewed || 0, hit = r.hit_rate, over = !!r.chairman_overconfident;
  let html = '<section><div class="sec-title">Review · 复盘自审计 <span class="cn">研判准确性回溯</span></div><div class="card">';
  html += '<div class="review-stats">'
    + '<div class="stat"><div class="k">已复盘</div><div class="v">'+reviewed+'</div></div>'
    + '<div class="stat"><div class="k">命中率</div><div class="v'+(hit!=null&&hit<0.5?' warn':'')+'">'+(hit==null?'—':pct(hit))+'</div></div>'
    + '<div class="stat"><div class="k">主席过度自信</div><div class="v'+(over?' warn':'')+'">'+(over?'是 ⚠':'否')+'</div></div></div>';
  const bm = r.by_member || {}, keys = Object.keys(bm);
  if (keys.length){
    html += '<div class="bymem"><div class="ev-title">分委员命中</div>'
      + keys.map(k => {
          const v = bm[k];
          const disp = (v && typeof v === 'object')
            ? Object.entries(v).map(e => e[0]+': '+ (typeof e[1]==='number' && e[1]<=1 ? pct(e[1]) : e[1])).join(' · ')
            : (typeof v === 'number' && v<=1 ? pct(v) : esc(String(v)));
          return '<div class="row"><span>'+esc(k)+'</span><span>'+esc(disp)+'</span></div>';
        }).join('') + '</div>';
  }
  const cal = r.calibration;
  if (cal){
    const vWarn = (cal.verdict === '过度自信') ? ' warn' : '';
    html += '<div class="review-stats" style="margin-top:14px">'
      + '<div class="stat"><div class="k">Brier</div><div class="v">'+cal.brier+'</div></div>'
      + '<div class="stat"><div class="k">ECE</div><div class="v">'+cal.ece+'</div></div>'
      + '<div class="stat"><div class="k">校准判定</div><div class="v'+vWarn+'">'+esc(cal.verdict)+'</div></div></div>';
    const rel = cal.reliability || [];
    if (rel.length){
      html += '<div class="bymem"><div class="ev-title">可靠性分箱（预测置信度 vs 实际命中；命中显著低于置信=过度自信）</div>'
        + rel.map(b => {
            const off = (b.accuracy < b.avg_conf - 0.1);
            return '<div class="row"><span>置信≈'+pct(b.avg_conf)+'（n='+b.n+'）</span>'
              + '<span'+(off?' style="color:var(--amber)"':'')+'>实际命中 '+pct(b.accuracy)+'</span></div>';
          }).join('') + '</div>';
    }
  }
  html += '<div class="review-note'+(over?' warn':'')+'">'+esc(r.note || '暂无复盘记录。')+'</div></div></section>';
  A.innerHTML = html;
  if (data.disclaimer) $('footDisc').textContent = data.disclaimer;
}

/* ---- QUANT ---- */
const QUANT_FACTORS = ["Mom_12_1", "Mom_6_1", "Rev_1", "Rev_5", "Rev_21",
  "TotalVol", "Vol_60", "DownVol", "HiLoRange", "MaxRet", "Hi52", "MA_Trend",
  "RangePos", "Amihud", "VolRatio", "PVCorr"];
// 每个因子的"大白话"含义：fam=家族，plain=显著时通俗说明（这条挑股规律到底在说什么）
const FACTOR_EXPLAIN = {
  Mom_12_1: {cn:"12-1月动量", fam:"动量", plain:"过去一年涨得好的股票倾向继续涨（强者恒强）"},
  Mom_6_1:  {cn:"6-1月动量",  fam:"动量", plain:"半年来的赢家倾向延续走强"},
  Rev_1:    {cn:"1日反转",    fam:"反转", plain:"昨天涨多的今天更可能回落——A股散户「追高易套」的典型特征"},
  Rev_5:    {cn:"5日反转",    fam:"反转", plain:"近一周涨多的股票接下来更可能回调"},
  Rev_21:   {cn:"1月反转",    fam:"反转", plain:"近一月涨多的下月倾向回落"},
  TotalVol: {cn:"20日波动",   fam:"低波", plain:"越「上蹿下跳」的股票未来收益越差（稳的反而更优）"},
  Vol_60:   {cn:"60日波动",   fam:"低波", plain:"长期波动大的股票后续更弱（低波异象）"},
  DownVol:  {cn:"下行波动",   fam:"低波", plain:"下跌时抖得厉害的股票后续更差"},
  HiLoRange:{cn:"日内振幅",   fam:"低波", plain:"天天大开大合的股票后续更弱"},
  MaxRet:   {cn:"最大单日涨幅",fam:"彩票效应", plain:"近期有过「暴涨日」的股票后续反而更差（博彩心理被高估）"},
  Hi52:     {cn:"52周高点接近度",fam:"趋势", plain:"越靠近一年新高的股票越倾向继续创新高"},
  MA_Trend: {cn:"均线趋势",   fam:"趋势", plain:"短均线压住长均线＝上升趋势，倾向延续"},
  RangePos: {cn:"区间位置",   fam:"趋势", plain:"价格在近20日高低带里越靠上，越偏强"},
  Amihud:   {cn:"非流动性",   fam:"流动性", plain:"越冷清难成交的股票要更高「流动性溢价」"},
  VolRatio: {cn:"量比",       fam:"量能", plain:"异常放量的股票后续更可能回落"},
  PVCorr:   {cn:"量价相关",   fam:"量能", plain:"放量涨/缩量跌（量价配合）的趋势更可信"},
};

function buildQuantNarrative(items){
  // items: [{f, r}] —— 据真实评估结果生成"大白话"解读（诚实：小样本/弃权如实说）
  const sig = items.filter(x => x.r.significant === 1);
  const notsig = items.filter(x => x.r.significant === 0);
  const abst = items.filter(x => x.r.significant !== 0 && x.r.significant !== 1);
  const ex = f => FACTOR_EXPLAIN[f] || {cn:f, plain:""};
  let h = '<div class="narr">';
  h += '<div class="narr-h">📊 这次体检说明了什么（大白话）</div>';
  h += '<p>本次在 <b>中证300 口径</b>（已剔除小盘股，防壳价值污染）上体检了 <b>'+items.length
     + '</b> 个「价量因子」。一个因子＝一条「挑股票的规律」；体检就是看每条规律在历史截面上<b>到底站不站得住脚</b>。</p>';
  if (sig.length){
    h += '<div class="narr-tag ok">✓ 站得住脚的规律（'+sig.length+' 条，统计显著）</div><ul class="narr-list">';
    sig.forEach(x => { const e = ex(x.f);
      h += '<li><b>'+esc(e.cn)+'</b>（'+esc(e.fam)+'）：'+esc(e.plain)
         + ' <span class="narr-ic up">RankIC '+(x.r.mean_rank_ic!=null?signed(x.r.mean_rank_ic,4):'—')
         + (x.r.ic_t_hac!=null?'，t='+fmt(x.r.ic_t_hac,2):'')+'</span></li>'; });
    h += '</ul>';
  } else {
    h += '<div class="narr-tag flat">— 本批没有统计显著的因子</div>'
       + '<p class="narr-dim">在当前样本上，没有哪条规律强到能排除「靠运气」。诚实地不下结论。</p>';
  }
  if (notsig.length){
    h += '<div class="narr-tag flat">— 暂时看不出规律（'+notsig.length+' 条，不显著）</div>'
       + '<p class="narr-dim">这些因子（'+notsig.slice(0,6).map(x=>esc(ex(x.f).cn)).join('、')
       + (notsig.length>6?' 等':'')+'）在当前样本上没有稳定信号——不显著就如实说不显著，不硬凑。</p>';
  }
  if (abst.length){
    h += '<div class="narr-tag warn">⊘ 数据不够、诚实弃权（'+abst.length+' 条）</div>'
       + '<p class="narr-dim">'+abst.map(x=>esc(ex(x.f).cn)).join('、')
       + ' —— 这些长窗口因子需要 ≥252 天历史才能算，当前积累不足。<b>系统宁可弃权也不硬猜</b>（这正是「诚实」设计）。</p>';
  }
  h += '<div class="narr-tag warn" style="margin-top:12px">⚠️ 必须说清的三件事</div><ul class="narr-list">'
     + '<li><b>样本规模决定可信度</b>：评估池越小，「显著」越可能是巧合。要全 300 只截面复核后，结论才真正算数。</li>'
     + '<li><b>因子级≠个股级</b>：一条规律整体有效，不等于某只票一定涨；须经三闸映射（家族过闸＋极端分位＋控风格后仍极端）。</li>'
     + '<li><b>研究型、不可实盘</b>：A股做空腿不可实现，只用多头超额作判据；这些是研究信号，<b>不构成投资建议</b>。</li></ul>';
  h += '<div class="narr-foot">怎么读这三个词 —— '
     + '<b>RankIC</b>：因子排名和未来收益的吻合度（±0.03 可用 / ±0.05 良好，对标 Qlib 真实基准 0.04–0.05）；'
     + '<b>显著</b>：统计上排除了「靠运气」（t 检验＋块自助双满足）；'
     + '<b>弃权</b>：数据/历史不足，主动不下结论。</div>';
  h += '</div>';
  return h;
}

async function renderQuant(){
  const A = $('analysis');
  A.innerHTML = '<section><div class="card"><div class="loading"><i></i><i></i><i></i> 载入因子体检…</div></div></section>';
  const items = [];
  for (const f of QUANT_FACTORS){
    let r = {};
    try { r = await getJSON('/api/factor_eval?factor_name=' + encodeURIComponent(f) + '&universe_filter=lsy'); }
    catch(e){ r = {}; }
    if (isErr(r)) r = {};
    items.push({f, r});
  }
  // 明细表（按 |RankIC| 降序，显著置顶）
  const sorted = items.slice().sort((a,b) => {
    const sa=a.r.significant===1?2:(a.r.significant===0?1:0), sb=b.r.significant===1?2:(b.r.significant===0?1:0);
    if (sa!==sb) return sb-sa;
    return Math.abs(b.r.mean_rank_ic||0) - Math.abs(a.r.mean_rank_ic||0);
  });
  let rows = '';
  for (const {f, r} of sorted){
    const e = FACTOR_EXPLAIN[f] || {cn:f, fam:''};
    const sig = r.significant === 1 ? '✓显著' : (r.significant === 0 ? '不显著' : '弃权');
    const cls = r.significant === 1 ? 'up' : (r.significant === 0 ? 'flat' : '');
    rows += '<div class="row"><span>'+esc(e.cn)+' <small style="color:var(--ink-faint)">'+esc(f)+'</small></span>'
          + '<span>'+(r.mean_rank_ic != null ? signed(r.mean_rank_ic, 4) : '—')+'</span>'
          + '<span>'+(r.ic_t_hac != null ? fmt(r.ic_t_hac, 2) : '—')+'</span>'
          + '<span class="'+cls+'"'+(cls!=='up'?' style="color:var(--amber)"':'')+'>'+esc(sig)+'</span></div>';
  }
  let html = '<section><div class="sec-title">Quant · 因子体检 <span class="cn">多因子选股 · L2 诚实评估</span></div>';
  // ① 大白话解读
  html += '<div class="card">' + buildQuantNarrative(items) + '</div>';
  // ② 评估池披露（回答"是不是全 A 股"）
  html += '<div class="card" style="margin-top:16px"><div class="ev-title">评估范围说明</div>'
        + '<div class="review-note"><b>这里展示的不是全部 A 股。</b> 因子体检评估池 = <b>中证300</b>'
        + '（A股最具代表性的 300 只蓝筹，约占 A股总市值 60%、但只占只数 ~6%）；盯盘墙 = <b>精选 38 只</b>跨 9 行业代表 + 6 指数；'
        + '个股研判则可输入<b>任意</b> A股代码。按设计走中证800/300 可投域（不做全市场 ~5000 只：日频全市场回测会引入幸存者/未来函数偏差且不可行）。</div></div>';
  // ③ 明细表
  html += '<div class="card" style="margin-top:16px"><div class="ev-title">因子 IC 体检明细（中证300 · 剔小票 lsy 口径 · 按显著性/强度排序）</div>'
        + '<div class="bymem"><div class="row" style="font-weight:600;opacity:.7"><span>因子</span><span>Rank-IC</span><span>t(HAC)</span><span>判定</span></div>'
        + rows + '</div></div>';
  html += '</section>';
  A.innerHTML = html;
  if ($('footDisc')) $('footDisc').textContent = '仅供学习研究，不构成投资建议。研究型，不可实盘。';
}

/* ---- TEACH ---- */
function renderTeach(data){
  const A = $('analysis');
  if (isErr(data)){ A.innerHTML = sectionNotice('教学内容加载失败', errMsg(data), true); return; }
  const content = data.content || {}, keys = Object.keys(content);
  let html = '<section><div class="sec-title">Teach · 教学 <span class="cn">术语与方法</span></div><div class="card"><div class="teach-list">';
  if (!keys.length){ html += '<div class="empty-soft">暂无教学内容。</div>'; }
  else { html += keys.map(k => '<div class="term"><div class="t">'+esc(k)+'</div><div class="d">'+esc(content[k])+'</div></div>').join(''); }
  html += '</div></div></section>';
  A.innerHTML = html;
  if (data.disclaimer) $('footDisc').textContent = data.disclaimer;
}

/* ---- STATUS modal ---- */
async function openStatus(){
  const modal = $('statusModal'); modal.classList.add('open');
  const body = $('statusBody');
  body.innerHTML = '<div class="loading"><i></i><i></i><i></i> 探测中…</div>';
  const s = await getJSON('/api/status');
  if (isErr(s)){ body.innerHTML = '<div class="notice err">状态接口不可用：'+esc(errMsg(s))+'</div>'; return; }
  const svc = [['gateway', s.gateway], ['agent', s.agent], ['storage', s.storage], ['ingestion', s.ingestion]];
  let html = svc.map(([k,v]) => {
    const ok = v === 'ok';
    return '<div class="srow"><span class="k"><span class="dot '+(ok?'ok':'bad')+'"></span>'+esc(k)+'</span>'
      + '<span class="'+(ok?'ok':'down')+'">'+esc(v==null?'?':v)+'</span></div>';
  }).join('');
  const m = s.metrics || {};
  html += '<div class="mc">metrics &nbsp; requests='+esc(m.requests==null?'—':m.requests)
    + ' · finance='+esc(m.finance==null?'—':m.finance)+'</div>';
  body.innerHTML = html;
}

/* ---------------- wiring ---------------- */
document.querySelectorAll('.modebtn[data-mode]').forEach(btn => {
  btn.addEventListener('click', () => { setMode(btn.dataset.mode); run(); });
});
$('symbol').addEventListener('keydown', e => { if (e.key === 'Enter') run(); });
$('statusBtn').addEventListener('click', openStatus);
$('backBtn').addEventListener('click', showBoard);
$('brandLogo').addEventListener('click', showBoard);
$('statusModal').addEventListener('click', e => { if (e.target.id === 'statusModal') e.currentTarget.classList.remove('open'); });
// 盯盘墙：事件委托点击个股 → 进入 detail
$('boardBody').addEventListener('click', e => {
  const t = e.target.closest('.ticker[data-sym]'); if (t) openDetail(t.dataset.sym);
});
$('boardBody').addEventListener('keydown', e => {
  if (e.key==='Enter' || e.key===' '){ const t = e.target.closest('.ticker[data-sym]'); if (t){ e.preventDefault(); openDetail(t.dataset.sym); } }
});
$('refreshBtn').addEventListener('click', () => { if (!$('boardView').classList.contains('hidden')) loadBoard(); });
document.addEventListener('visibilitychange', () => {
  if (!document.hidden && !$('boardView').classList.contains('hidden')) loadBoard();
});

/* ---------------- boot ---------------- */
tickClock();
clockTimer = setInterval(tickClock, 1000);
showBoard();   // 默认进入盯盘墙
