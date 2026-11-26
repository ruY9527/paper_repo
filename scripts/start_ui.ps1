# PaperFlow Studio — 一键启动本地 Web 控制台并打开浏览器

param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [int]$Port = 8000,
    [string]$Host = "127.0.0.1"
)

$ErrorActionPreference = "Continue"

# 激活虚拟环境（若存在）
$venv = Join-Path $ProjectRoot ".venv\Scripts\Activate.ps1"
if (Test-Path $venv) { & $venv }

Set-Location $ProjectRoot
$env:PYTHONPATH = Join-Path $ProjectRoot "src"

Write-Host "正在启动 PaperFlow Studio: http://$Host`:$Port" -ForegroundColor Green
python -m paperflow ui --host $Host --port $Port --open
