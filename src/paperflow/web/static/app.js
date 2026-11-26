/* PaperFlow Studio 前端逻辑 — Alpine.js */
function studio() {
  return {
    view: 'dashboard',
    codeFp: '', codeStale: false, codeStaleInfo: null,
    // 按日常使用顺序：总览 → 采集 → 论文管理 → 解析准备 → 解析 → 审阅 → 博客内容 → 发布 → 清理 → 配置
    navItems: [
      {id:'dashboard', icon:'📊', label:'总览仪表盘'},
      {id:'topics', icon:'🎯', label:'方向精准检索'},
      {id:'tasks', icon:'⚙️', label:'任务中心'},
      {id:'papers', icon:'📚', label:'论文账本'},
      {id:'paywall', icon:'🔒', label:'受限论文清单'},
      {id:'prompts', icon:'📝', label:'Prompt 工作室'},
      {id:'analyzer', icon:'🤖', label:'AI 解析中心'},
      {id:'staging', icon:'✍️', label:'待审工作台'},
      {id:'sites', icon:'🌐', label:'网站收录中心'},
      {id:'git', icon:'🚀', label:'Git 发布中心'},
      {id:'storage', icon:'💾', label:'存储治理'},
      {id:'settings', icon:'🎛️', label:'设置中心'},
    ],
    gitStatus: {branch:'',remote_url:'',is_ssh_remote:false,ahead_count:0,behind_count:0,
      has_changes:false,changes:[],added:0,modified:0,deleted:0,blog_site_url:null,is_git_repo:false},
    sshResult: '',
    pagesStatus: {deployed:false, gh_pages_remote:false, message:''},
    diffData: null,
    gitCommitMsg: '', gitPullFirst: false, gitCleanAfter: true,
    gitTaskId: null, gitProgress: {}, gitLogs: [], gitResultMsg: '',
    gitTab: 'commits', commits: [], pushLogs: [], commitSearch: '', commitDetail: null,
    // Phase 10：方向精准检索
    topicForm: {query:'', limit:20, onlyPrimaryYear:false, topVenuesOnly:false, autoDownload:true},
    topicPreview: null, topicTaskId: null, topicProgress: {}, topicLogs: [],
    topicResult: null, topicSubscriptions: [], topicHistory: [],
    topicTab: 'subs', newTopicSub: {name:'',query:''}, topicSubMsg: '',
    // Phase 11/15：AI 解析中心（引擎可插拔，列表与引擎解耦）
    analyzerEngine: 'claude_cli', analyzerEngines: [], harnessUrl: 'http://127.0.0.1:3080',
    analyzerStatus: {}, analyzerQueue: [], analyzerHistory: [], selectedPapers: [],
    queueFilter: {q:'',tier:'',status:'',limit:20,offset:0}, queueTotal: 0,
    analyzerProgressStats: {running:0,success:0,failed:0,interrupted:0,papers:{}},
    analyzerCheckResult: null, analyzerTaskId: null, analyzerProgress: {},
    analyzerLogs: [], analyzerResult: null,
    harnessModels: {ok:false, models:[], providers:[], message:''}, selectedModel: '', selectedProvider: '',
    importUid: null, importMarkdown: '', importMsg: '',
    importLocalMsg: '', importLocalOk: false,
    resultUid: null, resultPath: '', resultContent: '',
    runErrorDetail: null, progressDetail: null,
    // Phase 12：构建门禁 / 预览 / Prompt 工作室
    buildCheckResult: null, previewStatus: {running:false, url:null},
    promptTemplates: [], selectedPromptId: null, promptEditorBody: '',
    promptPreviewResult: null, promptSaveMsg: '', promptPreviewPaperUid: '',
    // Phase 13：受限论文清单
    paywallItems: [], paywallStats: {}, paywallFilter: {publisher:'',venue:'',manual_status:'PENDING_MANUAL',q:''},
    paywallDomains: [], paywallMsg: '', showDomains: false, newDomain: {domain:'',publisher:''},
    // Phase 14：网站收录中心
    siteItems: [], siteCats: [], siteStats: {}, siteFilter: {category_id:'',is_public:'',is_pinned:'',tag:'',sort:'recent',q:''},
    siteForm: {url:'',title:'',description:'',personal_note:'',category_id:'',tags:'',rating:0,is_pinned:false,is_public:true,favicon_url:''},
    editingSite: null, editForm: {},
    siteMsg: '', sitePublish: null, siteImportText: '', showSiteImport: false, showSiteCats: false, newSiteCat: {name:'',slug:'',icon:'🔗'},
    siteLayout: 'cards', siteTaskId: null, siteProgress: {}, siteLogs: [],
    summary: {},
    activeTask: null,
    liveLogs: [],
    currentTaskId: null,
    history: [], historyOffset: 0, historyLimit: 30, historyTotal: 0,
    logContent: '',
    papers: {items:[], total:0},
    paperFilter: {q:'', venue:'', tier:'', status:'', hasCode:false, radarOnly:false, limit:20, offset:0},
    pipelinePaper: null,
    venues: ['CVPR','ECCV','ICCV','NEURIPS','ICLR','AAAI','TPAMI','TIP','IJCV'],
    staging: [],
    selectedStaging: null,
    editorContent: '',
    validateMsg: '',
    blogArticles: {items:[],total:0,by_state:{}}, blogArticleView: null,
    storage: {pdfs:{size_mb:0,files:0},queue:{size_mb:0,dirs:0},state_db:{size_mb:0},cleanup_preview:null},
    settingsForm: {high:'',medium:'',exclude:'',authors:'',affils:'',tierS:50,tierA:25,autoPush:false},
    settingsMsg: '',
    addUrl: '', addVenue: '', addMsg: '',
    backfill: {from:'',to:'',preset:'last7',venueSet:[],sourceSet:[],dryRun:false},
    backfillMode: 'date', // date | query
    queryBackfill: {query:'', limit:20, onlyPrimaryYear:false, topVenuesOnly:false, autoDownload:true},
    queryHistory: [], queryHistoryMsg: '',
    backfillExpanded: false,
    backfillPresets: [
      {key:'yesterday', label:'昨天'},
      {key:'last3', label:'近 3 天'},
      {key:'last7', label:'近 7 天'},
      {key:'last30', label:'近 30 天'},
      {key:'thisMonth', label:'本月'},
      {key:'sinceWatermark', label:'自上次拉取'},
      {key:'custom', label:'自定义'},
    ],
    charts: {},

    async init() {
      await this.refreshAll();
      // 初始化补录区间为「近 7 天」，避免空白日期难以填写
      if (!this.backfill.from) this.applyPreset('last7');
      this.pollActive();
      setInterval(() => this.pollActive(), 3000);
      this.checkCodeVersion();
      setInterval(() => this.checkCodeVersion(), 10000);
    },
    async checkCodeVersion(){
      try{
        const d=await (await fetch('/api/system/version')).json();
        const fp=d.fingerprint;
        const prev=sessionStorage.getItem('paperflow_code_fp');
        if(!prev){ sessionStorage.setItem('paperflow_code_fp',fp); this.codeFp=fp; return; }
        if(prev!==fp && !this.codeStale){
          this.codeStale=true; this.codeStaleInfo={old:prev,now:fp,pid:d.pid};
        }
      }catch(e){}
    },

    currentTitle() {
      const item = this.navItems.find(i => i.id === this.view);
      return item ? item.label : 'PaperFlow Studio';
    },
    switchView(v) {
      this.view = v;
      if (v==='papers') this.loadPapers();
      if (v==='staging') { this.loadStaging(); this.loadBlogArticles(); }
      if (v==='storage') this.loadStorage();
      if (v==='settings') this.loadSettings();
      if (v==='git') this.loadGitStatus();
      if (v==='analyzer') { this.loadAnalyzerEngines(); this.loadAnalyzerStatus(); this.loadAnalyzerQueue(); this.loadAnalyzerHistory(); this.loadHarnessModels(); }
      if (v==='topics') { this.loadTopicSubs(); this.loadTopicHistory(); }
      if (v==='prompts') this.loadPromptTemplates();
      if (v==='paywall') this.loadPaywall();
      if (v==='sites') this.loadSites();
      if (v==='tasks') this.loadHistory();
      if (v==='dashboard') this.scheduleCharts();
      else this.destroyCharts();
    },

    kpiCards() {
      const k = this.summary.kpi || {};
      return [
        {label:'累计收录', value:k.total||0, hint:'今日新增 '+(k.today_new||0)},
        {label:'S 级精读', value:k.tier_s||0, hint:'A 级速览 '+(k.tier_a||0)},
        {label:'待分析', value:k.queued||0, hint:'待审 '+(k.staged||0)},
        {label:'已发布', value:k.published||0, hint:'已清理 '+(k.cleaned_count||0)},
        {label:'临时 PDF', value:(k.pdf_size_mb||0)+' MB', hint:'账本 '+(k.db_size_mb||0)+' MB'},
      ];
    },

    async refreshAll() {
      try {
        this.summary = await (await fetch('/api/dashboard/summary')).json();
        // 只在仪表盘可见时重绘图表：对 display:none 的 canvas 创建 Chart
        // 会导致 Chart.js 在绘制时拿到 null 的 2D context（reading 'save'）。
        this.scheduleCharts();
        // 同步刷新当前视图数据，避免"刷新"只更新 KPI 而表格停留在旧数据
        switch (this.view) {
          case 'tasks': this.loadHistory(); break;
          case 'papers': this.loadPapers(); break;
          case 'staging': this.loadStaging(); break;
          case 'storage': this.loadStorage(); break;
          case 'settings': this.loadSettings(); break;
          case 'git': this.loadGitStatus(); this.loadCommits(); this.loadPushLogs(); break;
          case 'topics': this.loadTopicSubs(); this.loadTopicHistory(); break;
          case 'analyzer': this.loadAnalyzerStatus(); this.loadAnalyzerQueue(); this.loadAnalyzerHistory(); break;
          case 'prompts': this.loadPromptTemplates(); break;
          case 'paywall': this.loadPaywall(); break;
        }
        // 若有活动任务，同步进度
        this.pollActive();
      } catch(e) { console.error(e); }
    },

    // 合并多次调度，避免刷新/切视图叠加导致重复 new Chart
    scheduleCharts() {
      if (this._chartTimer) { clearTimeout(this._chartTimer); this._chartTimer = null; }
      this._chartTimer = setTimeout(() => {
        this._chartTimer = null;
        this.renderCharts();
      }, 80);
    },

    // 图表可见且 DOM 就绪时才创建；切走视图时销毁实例，杜绝隐藏 canvas 绘制异常
    renderCharts() {
      if (typeof Chart === 'undefined') return;
      if (this.view !== 'dashboard') { this.destroyCharts(); return; }
      const el1 = document.getElementById('venueChart');
      const el2 = document.getElementById('trendChart');
      // offsetParent === null 表示元素（或其祖先 x-show）当前不可见
      if (!el1 || !el2 || !el1.offsetParent || !el2.offsetParent) return;
      const vd = this.summary.venue_distribution || [];
      if (this.charts.venue) this.charts.venue.destroy();
      this.charts.venue = new Chart(el1, {
        type:'bar',
        data:{labels:vd.map(v=>v.venue), datasets:[
          {label:'S',data:vd.map(v=>v.S),backgroundColor:'#ef4444'},
          {label:'A',data:vd.map(v=>v.A),backgroundColor:'#f59e0b'},
          {label:'B',data:vd.map(v=>v.B),backgroundColor:'#3b82f6'},
        ]},
        options:{responsive:true,maintainAspectRatio:false,animation:false,
                 scales:{x:{stacked:true},y:{stacked:true}}}
      });
      const trend = this.summary.daily_trend || [];
      if (this.charts.trend) this.charts.trend.destroy();
      this.charts.trend = new Chart(el2, {
        type:'line',
        data:{labels:trend.map(t=>t.date.slice(5)),datasets:[
          {label:'入库数',data:trend.map(t=>t.count),borderColor:'#6366f1',fill:true,tension:0.3}
        ]},
        options:{responsive:true,maintainAspectRatio:false,animation:false}
      });
    },

    destroyCharts() {
      if (this.charts.venue) { this.charts.venue.destroy(); this.charts.venue = null; }
      if (this.charts.trend) { this.charts.trend.destroy(); this.charts.trend = null; }
    },

    async startTask(command, params) {
      const res = await fetch('/api/tasks/'+command, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify(params||{})
      });
      if (res.status===409) { alert('已有任务在运行，请稍候'); return; }
      if (!res.ok) { alert('启动失败: '+await res.text()); return; }
      const data = await res.json();
      this.currentTaskId = data.task_id;
      this.liveLogs = [];
      this.subscribeStream(data.task_id);
      this.view = 'tasks';
    },

    subscribeStream(taskId) {
      // 先关闭上一条 SSE 连接，避免连续任务时旧连接残留、日志串台
      if (this._stream) { this._stream.close(); this._stream = null; }
      const es = new EventSource('/api/tasks/'+taskId+'/stream');
      this._stream = es;
      es.onmessage = (e) => {
        const ev = JSON.parse(e.data);
        this.activeTask = ev;
        this.liveLogs.push(ev);
        if (this.liveLogs.length>500) this.liveLogs.shift();
        if (['SUCCESS','FAILED','CANCELLED'].includes(ev.status)) {
          es.close(); if (this._stream===es) this._stream=null;
          this.loadHistory(); this.refreshAll();
        }
      };
      es.onerror = () => { es.close(); if (this._stream===es) this._stream=null; };
    },

    async pollActive() {
      try {
        const d = await (await fetch('/api/tasks/active')).json();
        if (d.active && (!this.activeTask || this.activeTask.task_id!==d.task_id)) {
          this.activeTask = d;
          this.currentTaskId = d.task_id;
          this.subscribeStream(d.task_id);
        } else if (!d.active && this.activeTask && ['RUNNING','PENDING'].includes(this.activeTask.status)) {
          this.activeTask = null;
        }
      } catch(e){}
    },

    async cancelTask(taskId) {
      await fetch('/api/tasks/'+taskId+'/cancel',{method:'POST'});
    },

    // ===== 统一时间格式（GMT+8 / Asia-Shanghai，yyyy-MM-dd HH:mm:ss）=====
    // 后端 now_iso() 带 +08:00，前端轮询曾产生 UTC 的 Z 串；此函数把任意 ISO
    // 时间戳统一按 GMT+8 显示，消除两套格式混用。
    fmtLogTime(iso){
      if(!iso) return '';
      try{
        const d=new Date(iso);
        if(isNaN(d.getTime())) return String(iso);
        const p=new Intl.DateTimeFormat('zh-CN',{
          timeZone:'Asia/Shanghai', year:'numeric', month:'2-digit', day:'2-digit',
          hour:'2-digit', minute:'2-digit', second:'2-digit', hour12:false
        }).formatToParts(d);
        const g=t=>p.find(x=>x.type===t)?.value||'';
        return `${g('year')}-${g('month')}-${g('day')} ${g('hour')}:${g('minute')}:${g('second')}`;
      }catch(e){ return String(iso); }
    },
    todayStr(){ return this.fmtLogTime(new Date().toISOString()).slice(0,10); },
    _gmt8Iso(){
      // 生成带 +08:00 偏移的 ISO 串，与后端 now_iso() 同格式
      const now=new Date();
      const local=new Date(now.getTime()+8*3600*1000);
      return local.toISOString().replace('Z','+08:00');
    },

    // ===== 手动补录：日期快捷预设 / 区间计算 / 校验 =====
    _fmtDate(d){ return this.fmtLogTime(d.toISOString()).slice(0,10); },
    watermarkLagText(){
      const wms=(this.summary.watermarks||[]).filter(w=>w.last_success_date);
      if(!wms.length) return '尚无成功拉取记录，建议先执行一次自动补录。';
      const max=Math.max(...wms.map(w=>Number(w.lag_days)||0));
      const worst=wms.filter(w=>(Number(w.lag_days)||0)===max).map(w=>w.source);
      return '落后最多 '+max+' 天（'+worst.join('、')+'），建议补录缺失日期。';
    },
    applyPreset(key){
      const today = new Date();
      const to = new Date(today);
      let from = new Date(today);
      if (key==='yesterday'){ from.setDate(today.getDate()-1); to.setDate(today.getDate()-1); }
      else if (key==='last3'){ from.setDate(today.getDate()-2); }
      else if (key==='last7'){ from.setDate(today.getDate()-6); }
      else if (key==='last30'){ from.setDate(today.getDate()-29); }
      else if (key==='thisMonth'){ from = new Date(today.getFullYear(), today.getMonth(), 1); }
      else if (key==='sinceWatermark'){
        // 从水位线里取最早的成功日期 +1 天；无水位线时回落到近 3 天
        const wms = (this.summary.watermarks||[]).filter(w=>w.last_success_date);
        if (wms.length){
          const dates = wms.map(w=>new Date(w.last_success_date+'T00:00:00'));
          const min = new Date(Math.min(...dates)); min.setDate(min.getDate()+1);
          from = min;
        } else { from.setDate(today.getDate()-2); }
      } else { this.backfill.preset='custom'; return; }
      this.backfill.from = this._fmtDate(from);
      this.backfill.to = this._fmtDate(to);
      this.backfill.preset = key;
    },
    backfillDays(){
      if(!this.backfill.from || !this.backfill.to) return 0;
      const a=new Date(this.backfill.from+'T00:00:00'), b=new Date(this.backfill.to+'T00:00:00');
      return Math.round((b-a)/86400000)+1;
    },
    backfillRangeText(){
      const n=this.backfillDays();
      return n>0 ? ('共 '+n+' 天') : '请选择起止日期';
    },
    backfillValid(){
      const n=this.backfillDays();
      return n>=1 && n<=60; // 与后端 max_auto_catchup_days 对齐
    },
    backfillHint(){
      const n=this.backfillDays();
      if(n<1) return '⚠ 起始日期不能晚于结束日期';
      if(n>60) return '⚠ 单次最多 60 天，请缩小范围或分段补录';
      return '✓ 区间合法（'+n+' 天）';
    },
    toggleBackfillVenue(v){
      const s=new Set(this.backfill.venueSet);
      s.has(v)?s.delete(v):s.add(v);
      this.backfill.venueSet=[...s];
    },
    toggleBackfillSource(s){
      const set=new Set(this.backfill.sourceSet);
      set.has(s)?set.delete(s):set.add(s);
      this.backfill.sourceSet=[...set];
    },
    async startBackfill() {
      if(!this.backfillValid()){ alert(this.backfillHint()); return; }
      const body = {
        date_from:this.backfill.from, date_to:this.backfill.to,
        venues:this.backfill.venueSet.length ? this.backfill.venueSet : null,
        sources:this.backfill.sourceSet.length ? this.backfill.sourceSet : null,
        dry_run:this.backfill.dryRun
      };
      await this.startTask('fetch', body);
    },
    async checkQueryHistory(){
      const q=(this.queryBackfill.query||'').trim();
      if(!q){ this.queryHistory=[]; this.queryHistoryMsg=''; return; }
      try{
        const d=await (await fetch('/api/tasks/query-history?q='+encodeURIComponent(q))).json();
        this.queryHistory=d.items||[];
        if(this.queryHistory.length){
          const h=this.queryHistory[0];
          this.queryHistoryMsg=`⚠ 该方向已检索过 ${this.queryHistory.length} 次，最近一次 ${this.fmtLogTime(h.created_at)}，新增 ${h.new_inserted_count} 篇；本次将补充新论文（UID 去重）`;
        } else { this.queryHistoryMsg='✓ 该方向首次检索'; }
      }catch(e){}
    },
    async startQueryBackfill(){
      const q=(this.queryBackfill.query||'').trim();
      if(!q){ alert('请输入研究方向或关键词'); return; }
      const body={query:q, limit:this.queryBackfill.limit,
        only_primary_year:this.queryBackfill.onlyPrimaryYear,
        top_venues_only:this.queryBackfill.topVenuesOnly,
        auto_download:this.queryBackfill.autoDownload};
      await this.startTask('query-backfill', body);
      this.checkQueryHistory();
    },

    async loadHistory() {
      const d = await (await fetch('/api/tasks/history?limit='+this.historyLimit+'&offset='+this.historyOffset)).json();
      this.history = d.items || [];
      this.historyTotal = d.total || 0;
    },
    historyPages(){ return Math.max(1, Math.ceil(this.historyTotal/this.historyLimit)); },
    historyPage(){ return Math.floor(this.historyOffset/this.historyLimit)+1; },
    historyPageBack(){ this.historyOffset=Math.max(0,this.historyOffset-this.historyLimit); this.loadHistory(); },
    historyPageNext(){ if(this.historyOffset+this.historyLimit<this.historyTotal){ this.historyOffset+=this.historyLimit; this.loadHistory(); } },
    async deleteHistory(id){
      if(!confirm('确认删除这条历史记录及其日志？')) return;
      const r=await fetch('/api/tasks/history/'+id,{method:'DELETE'});
      if(r.ok){ if(this.history.length===1 && this.historyOffset>0) this.historyOffset-=this.historyLimit; this.loadHistory(); }
    },
    async clearHistory(keep){
      const label=keep>0?('仅保留最近 '+keep+' 条'):'全部历史记录';
      if(!confirm('确认删除'+label+'？此操作不可撤销。')) return;
      const r=await fetch('/api/tasks/history?keep='+keep,{method:'DELETE'});
      const d=await r.json();
      this.historyOffset=0; this.loadHistory();
      alert('已删除 '+d.deleted+' 条记录');
    },
    async viewLog(id) {
      const d = await (await fetch('/api/tasks/history/'+id+'/log')).json();
      this.logContent = d.content || '无日志';
    },

    async addPaper() {
      const res = await fetch('/api/papers/add',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({url:this.addUrl,venue:this.addVenue||null})});
      if (res.ok) { const d=await res.json(); this.addMsg='✓ 已插队 '+d.paper_uid; this.addUrl=''; this.loadPapers(); }
      else this.addMsg='✗ 失败: '+await res.text();
    },

    async loadPapers() {
      const f = this.paperFilter;
      const q = new URLSearchParams();
      if(f.q) q.set('q',f.q); if(f.venue) q.set('venue',f.venue);
      if(f.tier) q.set('tier',f.tier); if(f.status) q.set('status',f.status);
      if(f.hasCode) q.set('has_code','true');
      if(f.radarOnly) q.set('radar_only','true');
      q.set('limit',f.limit); q.set('offset',f.offset);
      let d = await (await fetch('/api/papers?'+q)).json();
      // 越界保护：筛选/删改后当前页可能为空，自动回退到最后一页
      if(d.total>0 && f.offset>=d.total && !d.items.length){
        f.offset=Math.max(0,Math.ceil(d.total/f.limit)-1)*f.limit;
        q.set('offset',f.offset);
        d=await (await fetch('/api/papers?'+q)).json();
      }
      this.papers = d;
    },
    applyPaperFilter(){ this.paperFilter.offset=0; this.loadPapers(); },
    openPipeline(p){ this.pipelinePaper=p; },
    // 流水线阶段定义：名称/图标/说明
    pipelineSteps(){
      const p=this.pipelinePaper||{}; const f=p.stage_flags||{};
      const t=(s)=>s?this.fmtLogTime(s):'';
      return [
        {key:'fetched', icon:'📥', name:'采集入库', desc:'已从数据源抓取并写入账本', time:p.fetch_date?t(p.fetch_date):(p.created_at?t(p.created_at):''), done:!!f.fetched},
        {key:'downloaded', icon:'📄', name:'下载 PDF', desc:'S 级论文下载 PDF 并抽取架构图', time:p.downloaded_at?t(p.downloaded_at):'', done:!!f.downloaded},
        {key:'analyzed', icon:'🤖', name:'AI 解析', desc:'用提示词 + PDF 生成 13 节精读笔记', time:p.last_analysis_at?t(p.last_analysis_at):'', done:!!f.analyzed},
        {key:'published', icon:'🌐', name:'发布博客', desc:'同步到 GitHub Pages 公开站点', time:p.md_blog_path?'已同步':'', done:!!f.published},
      ];
    },
    pipelineNextAction(){
      const p=this.pipelinePaper; if(!p) return null;
      const f=p.stage_flags||{};
      if(!f.downloaded) return {label:'下载 PDF', hint:'到任务中心导出队列后下载 S 级 PDF', view:'tasks'};
      if(!f.analyzed) return {label:'去 AI 解析', hint:'在 AI 解析中心用提示词 + PDF 解析', view:'analyzer'};
      if(!f.published) return {label:'发布到博客', hint:'到待审工作台审阅后发布', view:'staging'};
      return null;
    },
    gotoPipelineView(v){ this.pipelinePaper=null; this.switchView(v); },
    resetPaperFilter(){
      this.paperFilter={q:'',venue:'',tier:'',status:'',hasCode:false,radarOnly:false,limit:this.paperFilter.limit,offset:0};
      this.loadPapers();
    },
    paperPage(){ return Math.floor(this.paperFilter.offset/this.paperFilter.limit)+1; },
    paperTotalPages(){ return Math.max(1,Math.ceil(this.papers.total/this.paperFilter.limit)); },
    paperHasNext(){ return this.paperFilter.offset+this.paperFilter.limit<this.papers.total; },
    pageBack(){ if(this.paperFilter.offset>0){this.paperFilter.offset=Math.max(0,this.paperFilter.offset-this.paperFilter.limit);this.loadPapers();} },
    pageNext(){ if(this.paperHasNext()){this.paperFilter.offset+=this.paperFilter.limit;this.loadPapers();} },
    async setTier(uid,tier){ await fetch('/api/papers/'+uid+'/tier',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({tier})}); this.loadPapers(); },
    async retryPaper(uid){ await fetch('/api/papers/'+uid+'/retry',{method:'POST'}); this.loadPapers(); },
    async copyBibtex(uid){ const d=await (await fetch('/api/papers/'+uid+'/bibtex')).json(); navigator.clipboard.writeText(d.bibtex); alert('BibTeX 已复制'); },

    stagingFilter: {q:'',status:'pending',limit:50,offset:0}, stagingTotal: 0,
    async loadStaging(){
      const f=this.stagingFilter, q=new URLSearchParams();
      if(f.q) q.set('q',f.q); if(f.status) q.set('status',f.status);
      q.set('limit',f.limit); q.set('offset',f.offset);
      try{ const d=await (await fetch('/api/staging?'+q)).json();
        this.staging=d.items||[]; this.stagingTotal=d.total||0;
      }catch(e){}
    },
    stagingPages(){ return Math.max(1,Math.ceil(this.stagingTotal/this.stagingFilter.limit)); },
    stagingPage(){ return Math.floor(this.stagingFilter.offset/this.stagingFilter.limit)+1; },
    stagingSearch(){ this.stagingFilter.offset=0; this.loadStaging(); },
    stagingPageBack(){ this.stagingFilter.offset=Math.max(0,this.stagingFilter.offset-this.stagingFilter.limit); this.loadStaging(); },
    stagingPageNext(){ if(this.stagingFilter.offset+this.stagingFilter.limit<this.stagingTotal){ this.stagingFilter.offset+=this.stagingFilter.limit; this.loadStaging(); } },
    // 按日期分组待审列表，日期倒序
    stagedGroups(){
      const map={};
      (this.staging||[]).forEach(s=>{ const d=s.date||'未分组'; (map[d]=map[d]||[]).push(s); });
      return Object.keys(map).sort().reverse().map(d=>({date:d,items:map[d]}));
    },
    async openStaging(uid){ this.selectedStaging=uid; const d=await (await fetch('/api/staging/'+uid)).json(); this.editorContent=d.content; this.validateMsg=''; },
    insertNote(){ this.editorContent+='\n\n> 💡 个人思考：'; },
    insertStar(){ this.editorContent+='\n\n⭐ 必读'; },
    insertRepro(){ this.editorContent+='\n\n🔥 计划复现'; },
    renderMd(txt){
      if(typeof marked==='undefined') return '';
      // 预览时去掉 YAML Frontmatter（它是元数据，不是正文）
      let body = txt||'';
      if(body.startsWith('---')){
        const end = body.indexOf('\n---', 3);
        if(end!==-1) body = body.slice(end+4).replace(/^\s*\n/,'');
      }
      return marked.parse(body);
    },
    async saveStaging(){ const d=await (await fetch('/api/staging/'+this.selectedStaging,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({content:this.editorContent})})).json(); this.validateMsg=d.valid?'✓ 校验通过':('✗ '+d.errors.join('; ')); this.loadStaging(); },
    async removeStaging(){ await fetch('/api/staging/'+this.selectedStaging,{method:'DELETE'}); this.selectedStaging=null;this.loadStaging(); },
    currentStagingValid(){ const s=this.staging.find(x=>x.paper_uid===this.selectedStaging); return !!(s && s.valid); },
    currentStagingPublished(){ const s=this.staging.find(x=>x.paper_uid===this.selectedStaging); return !!(s && s.published); },
    async viewPublishedBlog(){
      const s=this.staging.find(x=>x.paper_uid===this.selectedStaging);
      if(!s||!s.md_blog_path){ this.validateMsg='✗ 未找到博客文章路径'; return; }
      const r=await fetch('/api/blog/article-by-path?path='+encodeURIComponent(s.md_blog_path));
      if(!r.ok){ this.validateMsg='✗ 读取博客文章失败'; return; }
      this.blogArticleView={paper_uid:s.paper_uid,title:s.title,path:s.md_blog_path,content:await r.text()};
    },
    async publishStaging(uid){
      if(!uid) return;
      if(this.currentStagingPublished()){ this.validateMsg='✓ 这篇文章已发布，无需重复操作'; return; }
      if(!this.currentStagingValid()){ this.validateMsg='✗ 仅校验通过的文章可发布'; return; }
      const r=await fetch('/api/staging/'+uid+'/publish',{method:'POST'});
      const d=await r.json();
      // 关键：发布成功后必须刷新待审列表（拿到 published 状态），否则按钮不变、容易重复点击
      await this.loadStaging(); await this.loadBlogArticles();
      if(r.ok){ this.validateMsg='✓ '+(d.already_published?'已发布过':'已发布到博客')+': '+d.repo_rel; }
      else{ this.validateMsg='✗ 发布失败: '+(d.detail||JSON.stringify(d)); }
    },
    blogFilter: {q:'',limit:20,offset:0},
    async loadBlogArticles(){
      const f=this.blogFilter, q=new URLSearchParams();
      if(f.q) q.set('q',f.q); q.set('limit',f.limit); q.set('offset',f.offset);
      try{ this.blogArticles=await (await fetch('/api/blog/articles?'+q)).json(); }catch(e){}
    },
    blogPages(){ return Math.max(1,Math.ceil((this.blogArticles?.total||0)/this.blogFilter.limit)); },
    blogPage(){ return Math.floor(this.blogFilter.offset/this.blogFilter.limit)+1; },
    blogSearch(){ this.blogFilter.offset=0; this.loadBlogArticles(); },
    blogPageBack(){ this.blogFilter.offset=Math.max(0,this.blogFilter.offset-this.blogFilter.limit); this.loadBlogArticles(); },
    blogPageNext(){ if(this.blogFilter.offset+this.blogFilter.limit<(this.blogArticles?.total||0)){ this.blogFilter.offset+=this.blogFilter.limit; this.loadBlogArticles(); } },
    async viewBlogArticle(a){
      const r=await fetch('/api/blog/articles/'+a.paper_uid+'/content');
      if(!r.ok){ alert('读取博客文章失败'); return; }
      const d=await r.json(); this.blogArticleView={...a,content:d.content};
    },

    storageDetail: null,
    async loadStorage(){ this.storage=await (await fetch('/api/storage/summary')).json(); },
    async openStorageDetail(kind){
      const titles={pdfs:'临时 PDF 缓存',queue:'分析任务队列',cleanup:'可清理预览'};
      try{ const d=await (await fetch('/api/storage/files?kind='+kind)).json();
        this.storageDetail={kind:kind,title:titles[kind]||kind,total:d.total||0,items:d.items||[]};
      }catch(e){}
    },
    refreshStorage(){ return this.loadStorage(); },
    // 以 50MB 为满格的参考刻度，视觉化临时区占用
    storageBar(mb){ return Math.min(100, Math.round((Number(mb)||0)/50*100)); },

    async loadSettings(){
      const d=await (await fetch('/api/settings')).json(); const c=d.config||{};
      const ip=c.interest_profile||{};
      this.settingsForm.high=(ip.high_priority_keywords||[]).join(', ');
      this.settingsForm.medium=(ip.medium_priority_keywords||[]).join(', ');
      this.settingsForm.exclude=(ip.exclude_keywords||[]).join(', ');
      this.settingsForm.authors=(ip.tracked_authors||[]).join(', ');
      this.settingsForm.affils=(ip.tracked_affiliations||[]).join(', ');
      this.settingsForm.tierS=ip.thresholds?.tier_s??50;
      this.settingsForm.tierA=ip.thresholds?.tier_a??25;
      this.settingsForm.autoPush=!!(c.publish?.auto_git_push);
    },
    async saveSettings(){
      const d=await (await fetch('/api/settings')).json();
      const c=d.config||{}; const ip=c.interest_profile||{};
      const split=s=>s.split(',').map(x=>x.trim()).filter(Boolean);
      ip.high_priority_keywords=split(this.settingsForm.high);
      ip.medium_priority_keywords=split(this.settingsForm.medium);
      ip.exclude_keywords=split(this.settingsForm.exclude);
      ip.tracked_authors=split(this.settingsForm.authors);
      ip.tracked_affiliations=split(this.settingsForm.affils);
      ip.thresholds=ip.thresholds||{};
      ip.thresholds.tier_s=Number(this.settingsForm.tierS);
      ip.thresholds.tier_a=Number(this.settingsForm.tierA);
      c.interest_profile=ip;
      c.publish=c.publish||{}; c.publish.auto_git_push=!!this.settingsForm.autoPush;
      const res=await fetch('/api/settings',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({config:c})});
      if(res.ok){this.settingsMsg='✓ 已保存';}else{const e=await res.json();this.settingsMsg='✗ '+JSON.stringify(e.detail);}
    },
    async rescore(){ const d=await (await fetch('/api/settings/rescore',{method:'POST'})).json(); this.settingsMsg='✓ 已重新打分 '+d.rescored+' 篇'; },

    // ===== Phase 9：Git 发布中心 =====
    async loadGitStatus(){
      try{
        this.gitStatus = await (await fetch('/api/git/status')).json();
        if(!this.gitCommitMsg && (this.gitStatus.added+this.gitStatus.modified+this.gitStatus.deleted)>0)
          this.gitCommitMsg = 'docs: publish '+(this.gitStatus.added+this.gitStatus.modified+this.gitStatus.deleted)+' files ('+this.todayStr()+')';
        // 顺带查 gh-pages 部署状态
        try{ this.pagesStatus = await (await fetch('/api/git/pages-status')).json(); }catch(e){}
      }catch(e){ console.error(e); }
    },
    async testSsh(){
      this.sshResult='检测中…';
      const d=await (await fetch('/api/git/test-ssh',{method:'POST'})).json();
      this.sshResult=(d.ok?'✅ ':'❌ ')+d.message+(d.latency_ms?(' ('+d.latency_ms+'ms)'):'');
    },
    async gitPull(){
      const res=await fetch('/api/git/pull',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
      if(res.status===409){this.gitResultMsg='已有任务在运行';return;}
      const d=await res.json(); this.subscribeGitStream(d.task_id);
    },
    async viewDiff(path){
      const d=await (await fetch('/api/git/diff?path='+encodeURIComponent(path))).json();
      this.diffData=d;
    },
    async gitSubmit(endpoint, extra){
      const body={message:this.gitCommitMsg||('docs: publish ('+this.todayStr()+')'),
        push:true, pull_rebase_first:this.gitPullFirst, ...(extra||{})};
      const res=await fetch('/api/git/'+endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      if(res.status===409){this.gitResultMsg='已有任务在运行，请稍候';return;}
      if(!res.ok){this.gitResultMsg='启动失败: '+await res.text();return;}
      const d=await res.json(); this.gitTaskId=d.task_id; this.gitLogs=[]; this.gitResultMsg='';
      this.subscribeGitStream(d.task_id);
    },
    async gitCommitPush(){ await this.gitSubmit('commit-push',{}); },
    async gitPublishAndPush(){ await this.gitSubmit('publish-and-push',{clean:this.gitCleanAfter}); },
    subscribeGitStream(taskId){
      if (this._gitStream) { this._gitStream.close(); this._gitStream=null; }
      const es=new EventSource('/api/tasks/'+taskId+'/stream');
      this._gitStream=es;
      es.onmessage=(e)=>{
        const ev=JSON.parse(e.data);
        this.gitProgress=ev; this.gitLogs.push(ev);
        if(this.gitLogs.length>300) this.gitLogs.shift();
        if(['SUCCESS','FAILED','CANCELLED'].includes(ev.status)){
          es.close(); if(this._gitStream===es) this._gitStream=null;
          this.gitResultMsg=(ev.status==='SUCCESS'?'✅ 操作成功':'❌ '+ev.message);
          this.loadGitStatus(); this.loadCommits(); this.loadPushLogs();
        }
      };
      es.onerror=()=>{ es.close(); if(this._gitStream===es) this._gitStream=null; };
    },
    async loadCommits(){
      const d=await (await fetch('/api/git/commits?limit=30'+(this.commitSearch?'&q='+encodeURIComponent(this.commitSearch):''))).json();
      this.commits=d.items||[]; this.commitDetail=null;
    },
    async viewCommit(hash){ const d=await (await fetch('/api/git/commits/'+hash)).json(); this.commitDetail=d; },
    async loadPushLogs(){ const d=await (await fetch('/api/git/push-logs?limit=50')).json(); this.pushLogs=d.items||[]; },

    // ===== Phase 10：方向精准检索 =====
    topicYearPolicy(){
      const y=new Date().getFullYear();
      return this.topicForm.onlyPrimaryYear ? ('仅 '+y+' 年，严禁更早') : (y+' 优先 → '+(y-1)+' 兜底，≤'+(y-2)+' 硬过滤');
    },
    async previewTopicQuery(){
      if(!this.topicForm.query){ this.topicPreview=null; return; }
      try{
        const r=await fetch('/api/topics/preview-query',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query:this.topicForm.query})});
        if(r.ok) this.topicPreview=await r.json();
      }catch(e){ console.error(e); }
    },
    async loadTopicSubs(){
      try{ const d=await (await fetch('/api/topics/subscriptions')).json(); this.topicSubscriptions=d.items||[]; }catch(e){}
    },
    async loadTopicHistory(){
      try{ const d=await (await fetch('/api/topics/history?limit=50')).json(); this.topicHistory=d.items||[]; }catch(e){}
    },
    async startTopicSearch(){
      if(!this.topicForm.query) return;
      const body={query:this.topicForm.query,limit:this.topicForm.limit,
        only_primary_year:this.topicForm.onlyPrimaryYear,
        top_venues_only:this.topicForm.topVenuesOnly,
        auto_download:this.topicForm.autoDownload};
      const res=await fetch('/api/topics/search',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      if(res.status===409){ alert('已有任务在运行，请稍候'); return; }
      if(!res.ok){ alert('启动失败: '+await res.text()); return; }
      const d=await res.json(); this.topicTaskId=d.task_id; this.topicLogs=[]; this.topicResult=null;
      this.subscribeTopicStream(d.task_id);
    },
    async runTopicSubscriptions(){
      const res=await fetch('/api/topics/run-subscriptions',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
      if(res.status===409){ alert('已有任务在运行，请稍候'); return; }
      if(!res.ok){ alert('启动失败: '+await res.text()); return; }
      const d=await res.json(); this.topicTaskId=d.task_id; this.topicLogs=[]; this.topicResult=null;
      this.subscribeTopicStream(d.task_id);
    },
    subscribeTopicStream(taskId){
      // SSE + 轮询双通道：SSE 在代理/长连接场景可能不通，轮询兜底
      if(this._topicStream){ this._topicStream.close(); this._topicStream=null; }
      if(this._topicPoll){ clearInterval(this._topicPoll); this._topicPoll=null; }
      const applyEvent=(ev)=>{
        this.topicProgress=ev;
        const msg=ev.message||'';
        if(!this.topicLogs.length || this.topicLogs[this.topicLogs.length-1].timestamp!==ev.timestamp
           || this.topicLogs[this.topicLogs.length-1].message!==msg){
          this.topicLogs.push(ev); if(this.topicLogs.length>300) this.topicLogs.shift();
        }
        if(ev.result) this.topicResult=ev.result;
        if(ev.results) this.topicResult=ev.results[0]||null;
        if(['SUCCESS','FAILED','CANCELLED'].includes(ev.status)) this._finalizeTopicTask();
      };
      const es=new EventSource('/api/tasks/'+taskId+'/stream');
      this._topicStream=es;
      es.onmessage=(e)=>{ try{ applyEvent(JSON.parse(e.data)); }catch(err){} };
      es.onerror=()=>{ es.close(); if(this._topicStream===es) this._topicStream=null; };
      this._topicPoll=setInterval(async()=>{
        try{
          const r=await fetch('/api/tasks/'+taskId+'/poll'); if(!r.ok) return;
          const d=await r.json();
          const lastEv=(d.events&&d.events.length)?d.events[d.events.length-1]:null;
          applyEvent({task_id:taskId,status:d.status,stage:d.stage,percent:d.percent,
                      current:d.current,total:d.total,message:d.message,level:d.level||'INFO',
                      timestamp:lastEv?lastEv.timestamp:this._gmt8Iso(),
                      result:d.result&&d.result.results?d.result.results[0]:null});
          if(d.events&&d.events.length){
            const known=new Set(this.topicLogs.map(x=>x.timestamp+'|'+x.message));
            for(const ev of d.events){
              if(!known.has(ev.timestamp+'|'+ev.message)) this.topicLogs.push(ev);
            }
            if(this.topicLogs.length>300) this.topicLogs=this.topicLogs.slice(-300);
          }
        }catch(err){}
      },3000);
    },
    _finalizeTopicTask(){
      if(this._topicStream){ this._topicStream.close(); this._topicStream=null; }
      if(this._topicPoll){ clearInterval(this._topicPoll); this._topicPoll=null; }
      this.loadTopicSubs(); this.loadTopicHistory();
    },
    async cancelTopicTask(){
      if(this.topicTaskId) await fetch('/api/tasks/'+this.topicTaskId+'/cancel',{method:'POST'});
    },
    topicYearGroups(){
      if(!this.topicResult||!this.topicResult.papers) return [];
      const primary=this.topicResult.primary_year;
      const map={};
      this.topicResult.papers.forEach(p=>{ const y=p.pub_year||0; (map[y]=map[y]||[]).push(p); });
      return Object.keys(map).map(Number).sort((a,b)=>b-a).map(y=>({year:y,isPrimary:y===primary,items:map[y]}));
    },
    async promoteTopicPaper(uid){
      await fetch('/api/papers/'+uid+'/tier',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({tier:'S'})});
      alert('已升为 S 级；可到任务中心导出队列后下载 PDF');
    },
    async toggleTopicSub(s){
      const subs=this.topicSubscriptions.map(x=>({...x,enabled:x.slug===s.slug?!s.enabled:x.enabled}));
      await this.saveTopicSubs(subs);
    },
    async removeTopicSub(s){
      const subs=this.topicSubscriptions.filter(x=>x.slug!==s.slug);
      await this.saveTopicSubs(subs);
    },
    async addTopicSub(){
      if(!this.newTopicSub.name||!this.newTopicSub.query){ this.topicSubMsg='请填写名称与检索式'; return; }
      const slug=(this.newTopicSub.name||'').toLowerCase().replace(/[^a-z0-9\u4e00-\u9fff]+/g,'-').replace(/^-|-$/g,'')||('topic'+Date.now());
      const subs=[...this.topicSubscriptions,{...this.newTopicSub,slug,enabled:true,limit:20,only_primary_year:false,top_venues_only:false,primary_count:0,fallback_count:0}];
      await this.saveTopicSubs(subs);
      this.newTopicSub={name:'',query:''};
    },
    async saveTopicSubs(subs){
      // 只回传配置合法字段，剥离 primary_count/fallback_count/expanded_query 等只读字段
      const clean = subs.map(s=>({
        name:s.name, slug:s.slug, query:s.query, enabled:s.enabled,
        limit:s.limit, only_primary_year:s.only_primary_year, top_venues_only:s.top_venues_only
      }));
      const res=await fetch('/api/topics/subscriptions',{method:'PUT',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({subscriptions:clean})});
      if(res.ok){ this.topicSubMsg='✓ 已保存'; this.loadTopicSubs(); }
      else{ const e=await res.json(); this.topicSubMsg='✗ '+JSON.stringify(e.detail); }
    },

    // ===== Phase 11：AI 解析中心 =====
    async loadAnalyzerEngines(){
      try{
        const d=await (await fetch('/api/analyzer/engines')).json();
        this.analyzerEngines=d.items||[];
        if(!this.analyzerEngines.some(e=>e.id===this.analyzerEngine && e.available)){
          const first=this.analyzerEngines.find(e=>e.available);
          if(first) this.analyzerEngine=first.id;
        }
      }catch(e){}
    },
    currentEngine(){ return this.analyzerEngines.find(e=>e.id===this.analyzerEngine)||null; },
    async loadAnalyzerStatus(){
      try{ this.analyzerStatus=await (await fetch('/api/analyzer/status')).json(); }catch(e){}
      try{ this.analyzerProgressStats=await (await fetch('/api/analyzer/progress')).json(); }catch(e){}
    },
    paperAnalyzeState(uid){
      const p=(this.analyzerProgressStats.papers||{})[uid];
      if(!p||!p.last_status) return {label:'未解析',cls:''};
      const map={SUCCESS:{label:'✓ 已解析',cls:'ok'},RUNNING:{label:'◌ 解析中',cls:'warn'},
        INTERRUPTED:{label:'⚠ 中断',cls:'warn'},VALIDATION_FAILED:{label:'✗ 校验失败',cls:'err'},
        TIMEOUT:{label:'✗ 超时',cls:'err'},ERROR:{label:'✗ 错误',cls:'err'},CANCELLED:{label:'■ 已取消',cls:''}};
      return map[p.last_status]||{label:p.last_status,cls:'err'};
    },
    async resumeAnalysis(){
      const uids=this.selectedPapers.length?this.selectedPapers:this.analyzerQueue.map(q=>q.paper_uid);
      const r=await fetch('/api/analyzer/resume-check',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({paper_uids:uids})});
      const d=await r.json();
      if(!d.resume||!d.resume.length){ alert('没有需要续传的论文（已成功的会跳过）'); return; }
      let backend=this.analyzerEngine;
      const eng=this.currentEngine();
      if(eng && eng.mode==='manual') backend='harness_cli'; // 手动协作引擎不占批量 runner
      const res=await fetch('/api/analyzer/run',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({backend:backend,paper_uids:d.resume,model:this.selectedModel||null,provider:this.selectedProvider||null})});
      if(res.status===409){ alert('已有任务在运行'); return; }
      const t=await res.json(); this.analyzerTaskId=t.task_id; this.analyzerLogs=[]; this.analyzerResult=null;
      this.subscribeAnalyzerStream(t.task_id);
    },
    async loadHarnessModels(){
      try{
        this.harnessModels=await (await fetch('/api/analyzer/models')).json();
        // 默认选中：优先 DSH 当前默认(workbuddy/hy4flash)，否则第一个
        if(!this.selectedModel && this.harnessModels.models.length){
          const def=this.harnessModels.models.find(m=>m.id==='hy4flash') || this.harnessModels.models[0];
          this.selectedModel=def.id; this.selectedProvider=def.provider;
        }
      }catch(e){}
    },
    harnessModelsForSelect(){
      const ms=this.harnessModels.models||[];
      return this.selectedProvider ? ms.filter(m=>m.provider===this.selectedProvider) : ms;
    },
    async loadAnalyzerQueue(){
      const f=this.queueFilter, q=new URLSearchParams();
      if(f.q) q.set('q',f.q); if(f.tier) q.set('tier',f.tier); if(f.status) q.set('status',f.status);
      q.set('limit',f.limit); q.set('offset',f.offset);
      try{ const d=await (await fetch('/api/analyzer/queue?'+q)).json();
        this.analyzerQueue=d.items||[]; this.queueTotal=d.total||0;
      }catch(e){}
    },
    queuePages(){ return Math.max(1,Math.ceil(this.queueTotal/this.queueFilter.limit)); },
    queuePage(){ return Math.floor(this.queueFilter.offset/this.queueFilter.limit)+1; },
    queueSearch(){ this.queueFilter.offset=0; this.loadAnalyzerQueue(); },
    queuePageBack(){ this.queueFilter.offset=Math.max(0,this.queueFilter.offset-this.queueFilter.limit); this.loadAnalyzerQueue(); },
    queuePageNext(){ if(this.queueFilter.offset+this.queueFilter.limit<this.queueTotal){ this.queueFilter.offset+=this.queueFilter.limit; this.loadAnalyzerQueue(); } },
    async loadAnalyzerHistory(){ try{ this.analyzerHistory=(await (await fetch('/api/analyzer/history?limit=50')).json()).items||[]; }catch(e){} },
    async analyzerCheck(probe){
      this.analyzerCheckResult={ok:null,message:'检测中…'};
      let backend=this.analyzerEngine;
      const eng=this.currentEngine();
      if(eng && eng.mode==='manual') backend='harness_cli';
      const res=await fetch('/api/analyzer/check',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({backend:backend,probe:!!probe,model:this.selectedModel||null,provider:this.selectedProvider||null})});
      this.analyzerCheckResult=await res.json();
    },
    togglePaperSelect(uid){
      const s=new Set(this.selectedPapers); s.has(uid)?s.delete(uid):s.add(uid);
      this.selectedPapers=[...s];
    },
    selectAllQueue(on){ this.selectedPapers=on?this.analyzerQueue.map(q=>q.paper_uid):[]; },
    selectQueueByTier(tier){ this.selectedPapers=this.analyzerQueue.filter(q=>q.tier===tier).map(q=>q.paper_uid); },
    runAnalyzer(uids){
      const selected=uids||this.selectedPapers;
      if(!selected.length){ alert('请先选择论文'); return; }
      let backend=this.analyzerEngine;
      const eng=this.currentEngine();
      if(eng && eng.mode==='manual'){ alert('当前是手动协作引擎，请用「复制 Prompt / 回填」方式解析，或切换为全自动引擎'); return; }
      const res=fetch('/api/analyzer/run',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({backend:backend,paper_uids:selected,model:this.selectedModel||null,provider:this.selectedProvider||null})});
      res.then(async r=>{
        if(r.status===409){ alert('已有任务在运行'); return; }
        if(!r.ok){ alert('启动失败: '+await r.text()); return; }
        const d=await r.json(); this.analyzerTaskId=d.task_id; this.analyzerLogs=[]; this.analyzerResult=null;
        this.subscribeAnalyzerStream(d.task_id);
      });
    },
    showRunError(run){ this.runErrorDetail=run; },
    async openProgressDetail(cat){
      const labels={running:'解析中',success:'已解析',failed:'失败',interrupted:'中断待续'};
      try{
        const d=await (await fetch('/api/analyzer/progress/'+cat)).json();
        this.progressDetail={category:cat,label:labels[cat]||cat,count:d.count||0,items:d.items||[]};
      }catch(e){ this.progressDetail={category:cat,label:labels[cat]||cat,count:0,items:[]}; }
    },
    parsedErrorDetail(raw){
      if(!raw) return null;
      try{ const v=typeof raw==='string'?JSON.parse(raw):raw; return (v && Object.keys(v).length)?v:null; }catch(e){ return null; }
    },
    async viewResult(uid){
      const r=await fetch('/api/analyzer/result/'+uid);
      if(!r.ok){ alert('尚无解析结果，请先解析该论文'); return; }
      const d=await r.json(); this.resultUid=uid; this.resultPath=d.path; this.resultContent=d.content;
    },
    async openResultFromDetail(uid){ this.progressDetail=null; await this.viewResult(uid); },
    async reparseWithPdf(uid){
      // 用当前提示词原文 + 本地 PDF 重新解析该论文（刷新任务包 prompt 并复制 PDF）
      let backend=this.analyzerEngine;
      const eng=this.currentEngine();
      if(eng && eng.mode==='manual') backend='harness_cli';
      if(!confirm('将用「你的提示词原文 + 本地 PDF」重新解析这篇论文，覆盖旧的解析结果。确认继续？')) return;
      const res=await fetch('/api/analyzer/run',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({backend:backend,paper_uids:[uid],model:this.selectedModel||null,provider:this.selectedProvider||null})});
      if(res.status===409){ alert('已有任务在运行'); return; }
      if(!res.ok){ alert('启动失败: '+await res.text()); return; }
      const d=await res.json(); this.progressDetail=null; this.analyzerTaskId=d.task_id;
      this.analyzerLogs=[]; this.analyzerResult=null; this.subscribeAnalyzerStream(d.task_id);
    },
    jumpToStaging(uid){
      this.progressDetail=null; this.switchView('staging');
      // 待审列表加载后选中该论文
      this.loadStaging().then(()=>{ this.openStaging(uid); });
    },
    async syncToBlog(uid){
      const r=await fetch('/api/analyzer/sync-to-blog/'+uid,{method:'POST'});
      const d=await r.json();
      if(r.ok){ alert('✓ 已同步到博客仓库: '+d.blog_path); this.resultUid=null; }
      else{ alert('✗ 同步失败: '+JSON.stringify(d.detail)); }
    },
    runPipeline(){
      let engine=this.analyzerEngine;
      const eng=this.currentEngine();
      if(eng && eng.mode==='manual') engine='harness_cli';
      if(!confirm('一键全自动将依次执行：采集论文 → 导出队列 → AI解析（'+engine+'）→ 校验发布。确认开始？')) return;
      const body={engine:engine,steps:['fetch','queue','analyze','publish'],
                  model:this.selectedModel||null,provider:this.selectedProvider||null,
                  push:false,clean:false};
      const res=fetch('/api/tasks/pipeline',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      res.then(async r=>{
        if(r.status===409){ alert('已有任务在运行'); return; }
        if(!r.ok){ alert('启动失败: '+await r.text()); return; }
        const d=await r.json(); this.analyzerTaskId=d.task_id; this.analyzerLogs=[]; this.analyzerResult=null;
        this.subscribeAnalyzerStream(d.task_id);
      });
    },
    async cancelAnalyzerTask(){
      if(this.analyzerTaskId) await fetch('/api/tasks/'+this.analyzerTaskId+'/cancel',{method:'POST'});
    },
    subscribeAnalyzerStream(taskId){
      // 先停掉上一条任务的 SSE 与轮询，避免串台
      if(this._analyzerStream){ this._analyzerStream.close(); this._analyzerStream=null; }
      if(this._analyzerPoll){ clearInterval(this._analyzerPoll); this._analyzerPoll=null; }

      const applyEvent=(ev)=>{
        this.analyzerProgress=ev;
        const msg=ev.message||'';
        // 去重追加日志（SSE 与轮询会重复推送同一历史事件）
        if(!this.analyzerLogs.length || this.analyzerLogs[this.analyzerLogs.length-1].timestamp!==ev.timestamp
           || this.analyzerLogs[this.analyzerLogs.length-1].message!==msg){
          this.analyzerLogs.push(ev); if(this.analyzerLogs.length>400) this.analyzerLogs.shift();
        }
        if(ev.results) this.analyzerResult={count:ev.results.length};
        if(ev.result && ev.result.count!==undefined) this.analyzerResult=ev.result;
        if(['SUCCESS','FAILED','CANCELLED'].includes(ev.status)) this._finalizeAnalyzerTask();
      };

      // SSE 实时通道
      const es=new EventSource('/api/tasks/'+taskId+'/stream'); this._analyzerStream=es;
      es.onmessage=(e)=>{ try{ applyEvent(JSON.parse(e.data)); }catch(err){} };
      es.onerror=()=>{ es.close(); if(this._analyzerStream===es) this._analyzerStream=null; };
      // 定时轮询兜底：每 3 秒主动拉取一次状态与日志，SSE 不通也能看到进度
      this._analyzerPoll=setInterval(async()=>{
        try{
          const r=await fetch('/api/tasks/'+taskId+'/poll'); if(!r.ok) return;
          const d=await r.json();
          // 用后端最后一条事件的时间戳，避免轮询自造 timestamp 导致日志每 3 秒重复
          const lastEv=(d.events&&d.events.length)?d.events[d.events.length-1]:null;
          applyEvent({task_id:taskId,status:d.status,stage:d.stage,percent:d.percent,
                      current:d.current,total:d.total,message:d.message,level:d.level||'INFO',
                      timestamp:lastEv?lastEv.timestamp:this._gmt8Iso(),
                      results:d.result&&d.result.results?d.result.results:null});
          // 用后端历史事件补全日志（SSE 遗漏时）
          if(d.events && d.events.length){
            const known=new Set(this.analyzerLogs.map(x=>x.timestamp+'|'+x.message));
            for(const ev of d.events){
              if(!known.has(ev.timestamp+'|'+ev.message)){ this.analyzerLogs.push(ev); }
            }
            if(this.analyzerLogs.length>400) this.analyzerLogs=this.analyzerLogs.slice(-400);
          }
        }catch(err){}
      },3000);
    },
    _finalizeAnalyzerTask(){
      if(this._analyzerStream){ this._analyzerStream.close(); this._analyzerStream=null; }
      if(this._analyzerPoll){ clearInterval(this._analyzerPoll); this._analyzerPoll=null; }
      this.loadAnalyzerStatus(); this.loadAnalyzerQueue(); this.loadAnalyzerHistory();
    },
    async copyPrompt(uid){
      const d=await (await fetch('/api/analyzer/prompt/'+uid)).json();
      navigator.clipboard.writeText(d.prompt); alert('Prompt 已复制（'+d.chars+' 字符），粘贴到 DeepSeek Harness 即可');
    },
    async copyBatchInstruction(){
      const d=await (await fetch('/api/analyzer/batch-instruction')).json();
      navigator.clipboard.writeText(d.instruction); alert('整批执行指令已复制');
    },
    openImport(uid){ this.importUid=uid; this.importMarkdown=''; this.importMsg=''; },
    async submitImport(){
      if(!this.importMarkdown.trim()){ this.importMsg='请先粘贴 Markdown'; return; }
      const res=await fetch('/api/analyzer/import-md/'+this.importUid,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({markdown:this.importMarkdown})});
      if(res.ok){ this.importMsg='✓ 已校验入库'; this.loadAnalyzerQueue(); this.loadAnalyzerHistory(); setTimeout(()=>this.importUid=null,800); }
      else{ const e=await res.json(); this.importMsg='✗ '+JSON.stringify(e.detail); }
    },
    async onImportLocalPdfs(ev){
      // 文件选择框 change 或整页 drop 都走这里
      const files = ev.dataTransfer ? Array.from(ev.dataTransfer.files) : Array.from(ev.target.files||[]);
      const pdfs = files.filter(f=>f.name.toLowerCase().endsWith('.pdf'));
      if(!pdfs.length){ this.importLocalOk=false; this.importLocalMsg='✗ 请选择 PDF 文件'; return; }
      let ok=0, fail=0;
      for(const f of pdfs){
        const fd=new FormData(); fd.append('file', f);
        const res=await fetch('/api/analyzer/import-local-pdf',{method:'POST',body:fd});
        if(res.ok){ ok++; } else { fail++; }
      }
      this.importLocalOk = ok>0;
      this.importLocalMsg = '✓ 已导入 '+ok+' 篇本地 PDF'+(fail?('，失败 '+fail+' 篇'):'')+'，已加入待解析队列';
      this.loadAnalyzerQueue(); this.loadAnalyzerStatus();
      if(ev.target && ev.target.value){ ev.target.value=''; }
    },

    // ===== Phase 12：构建门禁 / 预览 / Prompt 工作室 =====
    async runBuildCheck(){
      this.buildCheckResult=null;
      const res=await fetch('/api/blog/build-check',{method:'POST'});
      this.buildCheckResult=await res.json();
    },
    async loadPreviewStatus(){
      try{ this.previewStatus=await (await fetch('/api/blog/preview/status')).json(); }catch(e){}
    },
    async togglePreview(){
      if(this.previewStatus.running){
        await fetch('/api/blog/preview/stop',{method:'POST'});
      }else{
        const r=await fetch('/api/blog/preview/start',{method:'POST'});
        this.previewStatus=await r.json();
      }
      this.loadPreviewStatus();
    },
    async loadPromptTemplates(){
      try{ const d=await (await fetch('/api/prompts')).json(); this.promptTemplates=d.items||[]; }catch(e){}
    },
    async openPrompt(id){
      const d=await (await fetch('/api/prompts/'+id)).json();
      this.selectedPromptId=id; this.promptEditorBody=d.body||''; this.promptSaveMsg=''; this.promptPreviewResult=null;
    },
    async savePrompt(){
      if(!this.selectedPromptId){ return; }
      const res=await fetch('/api/prompts/'+this.selectedPromptId,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({body:this.promptEditorBody})});
      const d=await res.json();
      if(res.ok){ this.promptSaveMsg='✓ 已保存'+(d.warnings&&d.warnings.length?('（提醒：'+d.warnings.join('; ')+')'):''); }
      else{ this.promptSaveMsg='✗ '+JSON.stringify(d.detail); }
    },
    async resetPrompt(){
      if(!this.selectedPromptId){ return; }
      await fetch('/api/prompts/'+this.selectedPromptId+'/reset',{method:'POST'});
      this.openPrompt(this.selectedPromptId); this.promptSaveMsg='✓ 已恢复默认';
    },
    async previewPrompt(paperUid){
      if(!this.selectedPromptId||!paperUid){ return; }
      const d=await (await fetch('/api/prompts/'+this.selectedPromptId+'/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({paper_uid:paperUid})})).json();
      this.promptPreviewResult=d;
    },
    insertPromptVar(v){
      // 简单追加到编辑器末尾（光标处插入需更复杂逻辑，此处采用追加）
      this.promptEditorBody += '{{'+v+'}}';
    },

    // ===== Phase 13：受限论文清单 =====
    async loadPaywall(){
      const f=this.paywallFilter;
      const q=new URLSearchParams();
      if(f.publisher) q.set('publisher',f.publisher);
      if(f.venue) q.set('venue',f.venue);
      if(f.manual_status) q.set('manual_status',f.manual_status);
      if(f.q) q.set('q',f.q);
      const d=await (await fetch('/api/paywall/papers?'+q)).json();
      this.paywallItems=d.items||[]; this.paywallStats=d.stats||{};
    },
    async loadPaywallDomains(){
      const d=await (await fetch('/api/paywall/domains')).json();
      this.paywallDomains=d.domains||[];
    },
    async paywallRescue(uid){
      await fetch('/api/paywall/papers/'+uid+'/rescue',{method:'POST'});
      this.loadPaywall(); this.paywallMsg='✓ 已触发 arXiv 抢救';
    },
    async paywallFallbackAbstract(uid){
      await fetch('/api/paywall/papers/'+uid+'/fallback-abstract',{method:'POST'});
      this.loadPaywall();
    },
    async paywallIgnore(uid){
      await fetch('/api/paywall/papers/'+uid,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({manual_status:'IGNORED'})});
      this.loadPaywall();
    },
    async paywallScanInbox(){
      const d=await (await fetch('/api/paywall/scan-inbox',{method:'POST'})).json();
      this.paywallMsg='✓ 匹配 '+d.matched+' 篇，未匹配 '+d.unmatched+' 篇';
      this.loadPaywall();
    },
    async paywallExport(fmt){
      window.open('/api/paywall/export?format='+fmt,'_blank');
    },
    async paywallUpload(uid, file){
      const fd=new FormData(); fd.append('file', file);
      const res=await fetch('/api/paywall/papers/'+uid+'/upload-pdf',{method:'POST',body:fd});
      if(res.ok){ this.paywallMsg='✓ 补传成功'; this.loadPaywall(); }
      else{ const e=await res.json(); this.paywallMsg='✗ '+JSON.stringify(e.detail); }
    },
    onPaywallDrop(uid, ev){
      const f=ev.dataTransfer.files[0];
      if(f && f.name.toLowerCase().endsWith('.pdf')) this.paywallUpload(uid, f);
      else this.paywallMsg='✗ 请拖入 PDF 文件';
    },
    async addPaywallDomain(){
      if(!this.newDomain.domain){ this.paywallMsg='✗ 请填域名'; return; }
      const domains=[...this.paywallDomains, {...this.newDomain, note:''}];
      const res=await fetch('/api/paywall/domains',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({domains})});
      if(res.ok){ this.paywallMsg='✓ 已保存'; this.newDomain={domain:'',publisher:''}; this.loadPaywallDomains(); }
      else{ const e=await res.json(); this.paywallMsg='✗ '+JSON.stringify(e.detail); }
    },

    // ===== Phase 14：网站收录中心 =====
    async loadSites(){
      const f=this.siteFilter;
      const qs=new URLSearchParams();
      if(f.category_id) qs.set('category_id',f.category_id);
      if(f.is_public!=='') qs.set('is_public',f.is_public);
      if(f.is_pinned!=='') qs.set('is_pinned',f.is_pinned);
      if(f.sort) qs.set('sort',f.sort);
      if(f.q) qs.set('q',f.q);
      try{ const d=await (await fetch('/api/sites?'+qs)).json(); this.siteItems=d.items||[]; this.siteStats=d.stats||{}; }catch(e){}
      try{ const c=await (await fetch('/api/sites/categories')).json(); this.siteCats=c.items||[]; }catch(e){}
      try{ this.sitePublish=await (await fetch('/api/sites/publish-status')).json(); }catch(e){}
    },
    async publishSites(){
      // 闭环：先同步导航页（本地生成），再跳到 Git 发布中心一键推送
      const r=await fetch('/api/sites/sync-blog',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
      if(!r.ok){ alert('生成导航页失败'); return; }
      const d=await r.json();
      this.siteMsg='✓ 导航页已生成（'+d.public_count+' 个公开网站），请到 Git 发布中心推送';
      this.loadSites(); this.switchView('git');
    },
    siteCatName(id){ const c=this.siteCats.find(x=>x.id===id); return c?c.name:'—'; },
    allSiteTags(){
      const set=new Set(); this.siteItems.forEach(s=>JSON.parse(s.tags_json||'[]').forEach(t=>set.add(t)));
      return [...set].sort();
    },
    async recordVisit(s){ try{ await fetch('/api/sites/'+s.id+'/visit',{method:'POST'}); }catch(e){} },
    recordVisitAndOpen(s){ this.recordVisit(s); window.open(s.normalized_url,'_blank','noopener'); },
    async copySiteUrl(s){
      try{ await navigator.clipboard.writeText(s.normalized_url); this.siteMsg='✓ 已复制网址'; }
      catch(e){ this.siteMsg='✗ 复制失败，请手动复制'; }
    },
    editSite(s){
      this.editingSite=s;
      this.editForm={url:s.url||s.normalized_url,title:s.title,description:s.description||'',
        personal_note:s.personal_note||'',category_id:s.category_id||'',
        tags:(JSON.parse(s.tags_json||'[]')||[]).join(','),rating:s.rating||0,
        is_pinned:!!s.is_pinned,is_public:s.is_public!==0};
    },
    async saveSiteEdit(){
      if(!this.editForm.url||!this.editForm.title){ this.siteMsg='✗ 网址与名称必填'; return; }
      const body={url:this.editForm.url,title:this.editForm.title,
        description:this.editForm.description,personal_note:this.editForm.personal_note,
        category_id:this.editForm.category_id||undefined,
        tags:this.editForm.tags.split(',').map(x=>x.trim()).filter(Boolean),
        rating:Number(this.editForm.rating)||0,is_pinned:this.editForm.is_pinned,
        is_public:this.editForm.is_public};
      const r=await fetch('/api/sites/'+this.editingSite.id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      if(r.ok){ this.siteMsg='✓ 已保存'; this.editingSite=null; this.loadSites(); }
      else{ const e=await r.json(); this.siteMsg='✗ '+(e.detail||'保存失败'); }
    },
    async fetchSiteMeta(){
      if(!this.siteForm.url){ this.siteMsg='✗ 请输入 URL'; return; }
      this.siteMsg='抓取中…';
      const d=await (await fetch('/api/sites/fetch-meta',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:this.siteForm.url})})).json();
      if(d.ok){ this.siteForm.title=d.title; this.siteForm.description=d.description; this.siteForm.favicon_url=d.favicon_url; this.siteMsg='✓ 抓取成功：'+d.title; }
      else{ this.siteForm.title=this.siteForm.title||d.domain||''; this.siteMsg='⚠ '+(d.warning||'抓取失败，请手填'); }
    },
    async saveSite(){
      const f=this.siteForm;
      if(!f.url){ this.siteMsg='✗ 请输入 URL'; return; }
      const body={url:f.url,title:f.title,description:f.description,personal_note:f.personal_note,
        category_id:Number(f.category_id)||this.siteCats[0]?.id||1,
        tags:f.tags.split(',').map(x=>x.trim()).filter(Boolean),rating:Number(f.rating)||0,
        favicon_url:f.favicon_url,is_pinned:f.is_pinned,is_public:f.is_public};
      const res=await fetch('/api/sites',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      if(res.ok){ this.siteMsg='✓ 已收录'; this.siteForm={url:'',title:'',description:'',personal_note:'',category_id:'',tags:'',rating:0,is_pinned:false,is_public:true,favicon_url:''}; this.loadSites(); }
      else{ const e=await res.json(); this.siteMsg='✗ '+(e.detail||JSON.stringify(e)); }
    },
    async toggleSitePin(s){ await fetch('/api/sites/'+s.id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({is_pinned:!s.is_pinned})}); this.loadSites(); },
    async toggleSitePublic(s){ await fetch('/api/sites/'+s.id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({is_public:!s.is_public})}); this.loadSites(); },
    async deleteSite(s){ if(!confirm('确认删除「'+s.title+'」？')) return; await fetch('/api/sites/'+s.id,{method:'DELETE'}); this.loadSites(); },
    async batchImportSites(){
      const res=await fetch('/api/sites/batch-import-urls',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:this.siteImportText,category_id:Number(this.siteForm.category_id)||undefined})});
      if(res.status===409){ this.siteMsg='✗ 已有任务在运行'; return; }
      const d=await res.json(); this.showSiteImport=false; this.siteImportText='';
      this.subscribeSiteStream(d.task_id);
    },
    subscribeSiteStream(taskId){
      if(this._siteStream){ this._siteStream.close(); }
      if(this._sitePoll){ clearInterval(this._sitePoll); }
      const apply=(ev)=>{
        this.siteProgress=ev;
        if(ev.message) this.siteLogs.push(ev);
        if(this.siteLogs.length>200) this.siteLogs.shift();
        if(['SUCCESS','FAILED','CANCELLED'].includes(ev.status)){
          if(this._siteStream){this._siteStream.close();this._siteStream=null;}
          if(this._sitePoll){clearInterval(this._sitePoll);this._sitePoll=null;}
          this.loadSites();
        }
      };
      const es=new EventSource('/api/tasks/'+taskId+'/stream'); this._siteStream=es;
      es.onmessage=e=>{try{apply(JSON.parse(e.data));}catch(err){}};
      es.onerror=()=>{es.close();this._siteStream=null;};
      this._sitePoll=setInterval(async()=>{
        try{ const r=await fetch('/api/tasks/'+taskId+'/poll'); if(!r.ok)return; const d=await r.json();
          apply({status:d.status,stage:d.stage,percent:d.percent,message:d.message,result:d.result,
                 level:d.level||'INFO',timestamp:this._gmt8Iso()}); }catch(err){}
      },3000);
    },
    async healthCheckSites(){
      const res=await fetch('/api/sites/health-check',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
      if(res.status===409){ this.siteMsg='✗ 已有任务在运行'; return; }
      const d=await res.json(); this.siteLogs=[]; this.subscribeSiteStream(d.task_id);
    },
    async syncSitesBlog(){
      const res=await fetch('/api/sites/sync-blog',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({layout:this.siteLayout})});
      const d=await res.json();
      this.siteMsg=d.ok?('✓ 已同步 '+d.public_count+' 个公开网站到博客导航页'):'✗ 同步失败';
    },
    async onSiteBookmarkFile(ev){
      const f=ev.target.files[0]; if(!f) return;
      const fd=new FormData(); fd.append('file',f);
      const res=await fetch('/api/sites/import-bookmarks',{method:'POST',body:fd});
      if(res.status===409){ this.siteMsg='✗ 已有任务在运行'; return; }
      if(!res.ok){ const e=await res.json(); this.siteMsg='✗ '+JSON.stringify(e.detail); return; }
      const d=await res.json(); this.showSiteImport=false;
      this.siteMsg='✓ 已解析 '+d.count+' 条书签，开始导入';
      this.subscribeSiteStream(d.task_id);
    },
    onSiteFileDrop(ev){
      const f=ev.dataTransfer.files[0];
      if(f && f.name.toLowerCase().endsWith('.html')) this.onSiteBookmarkFile({target:{files:[f]}});
      else this.siteMsg='✗ 请拖入 bookmarks.html 文件';
    },
    async addSiteCategory(){
      if(!this.newSiteCat.name||!this.newSiteCat.slug){ this.siteMsg='✗ 请填名称与 slug'; return; }
      const res=await fetch('/api/sites/categories',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(this.newSiteCat)});
      if(res.ok){ this.newSiteCat={name:'',slug:'',icon:'🔗'}; this.loadSites(); } else { const e=await res.json(); this.siteMsg='✗ '+JSON.stringify(e.detail); }
    },
  };
}
