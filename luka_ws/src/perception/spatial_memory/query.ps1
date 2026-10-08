param([string]$Query = '')
$encoded = [uri]::EscapeDataString($Query)
$result = Invoke-RestMethod -Uri "http://192.168.3.251:8091/search?q=$encoded" -TimeoutSec 10
if ($result.count -eq 0) {
    Write-Output '尚未记住匹配的物体。'
}
foreach ($item in $result.objects) {
    $distance = if ($null -ne $item.xyz_m) { '前方 {0:F2} 米，左右 {1:+0.00;-0.00;0.00} 米，上下 {2:+0.00;-0.00;0.00} 米' -f $item.xyz_m[2], $item.xyz_m[0], $item.xyz_m[1] } else { '暂无可靠深度' }
    $state = if ($item.currently_visible) { '当前可见' } else { '历史记忆' }
    Write-Output "$($item.label_zh)｜$state｜画面$($item.image_location_zh)｜$distance｜最后看到 $($item.last_seen_local)"
}
