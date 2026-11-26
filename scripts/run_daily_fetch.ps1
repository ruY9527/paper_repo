# PaperFlow 每日定时拉取脚本
# 依次执行 fetch + export-queue，输出日志并发送极简播报

param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$LogDir = (Join-Path $PSScriptRoot "..\workspace\logs"),
    [switch]$AutoAnalyze
)

$ErrorActionPreference = "Continue"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Force -Path $LogDir | Out-Null }
$dateStr = Get-Date -Format "yyyy-MM-dd"
$logFile = Join-Path $LogDir "daily_$dateStr.log"

function Write-Log($msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') | $msg"
    Write-Host $line
    Add-Content -Path $logFile -Value $line -Encoding UTF8
}

# 1. 激活虚拟环境（若存在）
$venv = Join-Path $ProjectRoot ".venv\Scripts\Activate.ps1"
if (Test-Path $venv) {
    & $venv
    Write-Log "已激活虚拟环境"
}

Set-Location $ProjectRoot
$env:PYTHONPATH = Join-Path $ProjectRoot "src"

# 2. fetch（自动补录 + 去重 + 打分 + 下载 S 级 PDF + 抽图）
Write-Log "===== PaperFlow 每日任务开始 ====="
$fetchOut = python -m paperflow fetch 2>&1
$fetchOut | ForEach-Object { Write-Log $_ }

# 2.5 topic-run（追新所有已启用的常驻方向订阅，与方向精准检索打通）
Write-Log "----- 方向订阅追新 -----"
$topicOut = python -m paperflow topic-run 2>&1
$topicOut | ForEach-Object { Write-Log $_ }

# 3. export-queue（重复导出按 UID 幂等）
$queueOut = python -m paperflow export-queue 2>&1
$queueOut | ForEach-Object { Write-Log $_ }

# 3.5 可选自动解析
if ($AutoAnalyze) {
    Write-Log "----- 自动解析队列 -----"
    $analyzeOut = python -m paperflow analyze 2>&1
    $analyzeOut | ForEach-Object { Write-Log $_ }
}

# 4. 从 SQLite 读取真实统计（QUEUED + DOWNLOADED 与解析中心同口径）
$statsCode = @'
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(sys.argv[1]) / "src"))
from paperflow.config import load_config
from paperflow.db.repository import PaperRepository
from paperflow.utils.timeutil import today_date

cfg = load_config()
repo = PaperRepository(cfg.db_path)
papers = repo.get_all_papers()
today = today_date().isoformat()
pending = {"QUEUED", "DOWNLOADED"}
analyzed = {"ANALYZED", "STAGED", "PUBLISHED", "CLEANED"}
print(json.dumps({
    "new_today": sum(p.fetch_date == today for p in papers),
    "tier_s": sum(p.tier == "S" for p in papers),
    "tier_a": sum(p.tier == "A" for p in papers),
    "pending": sum(p.status in pending for p in papers),
    "analyzed": sum(p.status in analyzed for p in papers),
    "published": sum(p.status in {"PUBLISHED", "CLEANED"} for p in papers),
}, ensure_ascii=False))
'@
$statsJson = $statsCode | python - $ProjectRoot
$stats = $statsJson | ConvertFrom-Json
$summary = "PaperFlow 日报：今日新增 $($stats.new_today) 篇；S/A $($stats.tier_s)/$($stats.tier_a) 篇；待解析 $($stats.pending) 篇；已解析 $($stats.analyzed) 篇；已发布 $($stats.published) 篇。日志：$logFile"
Write-Log $summary
Write-Log "===== PaperFlow 每日任务结束 ====="

# 5. 发送真实统计播报（桌面通知 + 可选 Webhook）
$notifier = @"
import sys
sys.path.insert(0, r'$ProjectRoot\src')
from paperflow.config import load_config
from paperflow.utils.notifier import notify_daily
cfg = load_config()
notify_daily(cfg, '''$summary''')
"@
$notifier | python - 2>&1 | ForEach-Object { Write-Log $_ }
