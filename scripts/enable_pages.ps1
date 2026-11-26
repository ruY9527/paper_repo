# Enable GitHub Pages (Source = gh-pages branch / root)
# Usage:
#   1) Set GH_TOKEN (fine-grained token with Contents:write + Pages:write, or classic repo scope)
#      $env:GH_TOKEN = "ghp_xxx"
#      powershell -ExecutionPolicy Bypass -File .\scripts\enable_pages.ps1
#   2) Without GH_TOKEN, the script only prints manual steps; no writes are performed.

$ErrorActionPreference = "Stop"
$Owner = "ruY9527"
$Repo = "paper_repo"
$Api = "https://api.github.com/repos/$Owner/$Repo/pages"
$PagesUrl = "https://$Owner.github.io/$Repo/"

function Invoke-GitHub {
    param([string]$Method, [string]$Uri, [object]$Body = $null)
    $headers = @{
        "Accept" = "application/vnd.github+json"
        "Authorization" = "Bearer $env:GH_TOKEN"
        "User-Agent" = "PaperFlow2026"
        "X-GitHub-Api-Version" = "2022-11-28"
    }
    $params = @{ Method = $Method; Uri = $Uri; Headers = $headers; TimeoutSec = 30 }
    if ($null -ne $Body) {
        $params.Body = ($Body | ConvertTo-Json -Depth 5)
        $params.ContentType = "application/json"
    }
    return Invoke-RestMethod @params
}

if (-not $env:GH_TOKEN) {
    Write-Host ""
    Write-Host "==============================================================" -ForegroundColor Yellow
    Write-Host "  GitHub Pages is NOT enabled. This is the ONLY cause of 404." -ForegroundColor Yellow
    Write-Host "  gh-pages branch content is ready; just enable Pages.        " -ForegroundColor Yellow
    Write-Host "==============================================================" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Method A (recommended, use installed gh CLI):" -ForegroundColor Cyan
    Write-Host "  1) run: gh auth login"
    Write-Host "  2) choose GitHub.com -> HTTPS -> Login with a web browser"
    Write-Host "  3) after auth, rerun: gh api --method POST repos/$Owner/$Repo/pages -f source[branch]=gh-pages -f source[path]=/"
    Write-Host ""
    Write-Host "Method B (manual web UI, ~30s):" -ForegroundColor Cyan
    Write-Host "  1. Open https://github.com/$Owner/$Repo/settings/pages"
    Write-Host "  2. Build and deployment -> Source: 'Deploy from a branch'"
    Write-Host "  3. Branch: 'gh-pages', folder: '/ (root)', click Save"
    Write-Host "  4. Visit $PagesUrl after 1-2 minutes"
    Write-Host ""
    Write-Host "Method C (auto with GH_TOKEN):" -ForegroundColor Cyan
    Write-Host "  set GH_TOKEN=<token>, then rerun this script"
    Write-Host ""
    exit 0
}

Write-Host "Checking Pages status..."
try {
    $current = Invoke-GitHub -Method GET -Uri $Api
    Write-Host "Pages already enabled: source=$($current.source.branch)/$($current.source.path), url=$($current.html_url)" -ForegroundColor Green
    exit 0
} catch {
    Write-Host "Pages not enabled. Enabling (source=gh-pages/root)..."
}

$body = @{
    source = @{ branch = "gh-pages"; path = "/" }
    build_type = "legacy"
}
try {
    $result = Invoke-GitHub -Method POST -Uri $Api -Body $body
    Write-Host "OK: GitHub Pages enabled -> $($result.html_url)" -ForegroundColor Green
    Write-Host "Site: $PagesUrl (usually live within 1-2 minutes)"
} catch {
    $msg = $_.Exception.Message
    if ($msg -match "409|already|exists") {
        Write-Host "Pages may already be configured. Check Settings -> Pages." -ForegroundColor Yellow
    } else {
        Write-Error "Failed to enable Pages: $msg"
    }
}
