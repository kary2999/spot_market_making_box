<?php
/**
 * 铺单配置生成器 - 控制面板
 *
 * 用法:
 *   php control_panel.php          # 显示最新50条日志
 *   php control_panel.php --tail   # 持续监控（每3秒刷新）
 *   php control_panel.php --stats  # 显示统计摘要
 *   php control_panel.php --clear  # 清空日志
 */

define('LOG_FILE',    __DIR__ . '/logs/operations.log');
define('OUTPUT_DIR',  __DIR__ . '/output');
define('REFRESH_SEC', 3);

// ==================== 日志读取 ====================

function read_logs($limit = 50)
{
    if (!file_exists(LOG_FILE)) {
        return array();
    }
    $lines = file(LOG_FILE, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
    $logs  = array();
    foreach (array_slice($lines, -$limit) as $line) {
        $data = json_decode($line, true);
        if ($data) {
            $logs[] = $data;
        }
    }
    return $logs;
}

function read_all_logs()
{
    if (!file_exists(LOG_FILE)) {
        return array();
    }
    $lines = file(LOG_FILE, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
    $logs  = array();
    foreach ($lines as $line) {
        $data = json_decode($line, true);
        if ($data) {
            $logs[] = $data;
        }
    }
    return $logs;
}

// ==================== 输出工具 ====================

function color($text, $code)
{
    return "\033[{$code}m{$text}\033[0m";
}

function status_color($status)
{
    if ($status === 'OK')   return color($status, '32');   // 绿
    if ($status === 'FAIL') return color($status, '31');   // 红
    return color($status, '33');                           // 黄
}

function action_color($action)
{
    $colors = array(
        'BATCH_START'  => '36',  // 青
        'BATCH_END'    => '36',
        'API_LOCAL'    => '34',  // 蓝
        'API_MARKET'   => '34',
        'SQL_WRITE'    => '35',  // 紫
        'GENERATE'     => '33',  // 黄
    );
    $code = isset($colors[$action]) ? $colors[$action] : '37';
    return color($action, $code);
}

// ==================== 面板视图 ====================

function show_header()
{
    $time = date('Y-m-d H:i:s');
    echo "\033[H\033[2J";  // 清屏
    echo color("╔══════════════════════════════════════════════════╗", '36') . "\n";
    echo color("║      铺单配置生成器 · 控制面板                   ║", '36') . "\n";
    echo color("║  " . str_pad($time, 48) . "║", '36') . "\n";
    echo color("╚══════════════════════════════════════════════════╝", '36') . "\n\n";
}

function show_output_stats()
{
    if (!is_dir(OUTPUT_DIR)) {
        echo color(" [输出目录不存在]", '31') . "\n\n";
        return;
    }

    $files   = glob(OUTPUT_DIR . '/*.sql');
    $count   = count($files);
    $batchExists = file_exists(OUTPUT_DIR . '/batch_all.sql');
    $batchSize   = $batchExists ? round(filesize(OUTPUT_DIR . '/batch_all.sql') / 1024, 1) : 0;

    echo color(" 📁 输出文件", '33') . "\n";
    echo str_repeat('─', 52) . "\n";
    echo sprintf("  SQL 文件数  : %d 个\n", $count);
    if ($batchExists) {
        echo sprintf("  汇总文件    : batch_all.sql  (%s KB)\n", $batchSize);
    }
    echo "\n";
}

function show_logs($limit = 50)
{
    $logs = read_logs($limit);

    echo color(" 📋 最近操作日志（最新 {$limit} 条）", '33') . "\n";
    echo str_repeat('─', 80) . "\n";

    if (empty($logs)) {
        echo color("  暂无日志记录\n", '37');
    } else {
        echo sprintf(" %-19s  %-14s  %-6s  %s\n", '时间', '操作', '状态', '详情');
        echo str_repeat('─', 80) . "\n";
        foreach ($logs as $log) {
            $status = isset($log['status']) ? $log['status'] : '';
            $detail = isset($log['detail']) ? $log['detail'] : '';
            // 截断长详情
            if (strlen($detail) > 50) {
                $detail = substr($detail, 0, 47) . '...';
            }
            printf(" %-19s  %-14s  %-6s  %s\n",
                $log['time'],
                action_color($log['action']),
                status_color($status),
                $detail
            );
        }
    }
    echo "\n";
}

function show_stats()
{
    $logs = read_all_logs();

    $stats = array(
        'total'        => count($logs),
        'api_ok'       => 0,
        'api_fail'     => 0,
        'sql_writes'   => 0,
        'batch_runs'   => 0,
        'symbols_done' => array(),
    );

    foreach ($logs as $log) {
        if ($log['action'] === 'API_MARKET') {
            if ($log['status'] === 'OK')   $stats['api_ok']++;
            if ($log['status'] === 'FAIL') $stats['api_fail']++;
        }
        if ($log['action'] === 'SQL_WRITE') {
            $stats['sql_writes']++;
            if (preg_match('/file=.*?(\w+_usdt)_pid/i', $log['detail'], $m)) {
                $stats['symbols_done'][$m[1]] = true;
            }
        }
        if ($log['action'] === 'BATCH_START') {
            $stats['batch_runs']++;
        }
    }

    echo color(" 📊 统计摘要", '33') . "\n";
    echo str_repeat('─', 52) . "\n";
    printf("  总日志条数  : %d\n",   $stats['total']);
    printf("  API 成功    : %d\n",   $stats['api_ok']);
    printf("  API 失败    : %d\n",   $stats['api_fail']);
    printf("  SQL 写入次数: %d\n",   $stats['sql_writes']);
    printf("  批量运行次数: %d\n",   $stats['batch_runs']);
    printf("  已生成交易对: %d 个\n", count($stats['symbols_done']));
    echo "\n";

    if (!empty($stats['symbols_done'])) {
        echo color(" ✅ 已生成交易对列表\n", '32');
        echo str_repeat('─', 52) . "\n";
        $syms = array_keys($stats['symbols_done']);
        sort($syms);
        $cols = 4;
        foreach (array_chunk($syms, $cols) as $row) {
            echo '  ' . implode('  ', array_map(function($s) {
                return str_pad(strtoupper($s), 12);
            }, $row)) . "\n";
        }
        echo "\n";
    }
}

// ==================== 主入口 ====================

$opts = getopt('', array('tail', 'stats', 'clear', 'lines:'));

if (isset($opts['clear'])) {
    if (file_exists(LOG_FILE)) {
        file_put_contents(LOG_FILE, '');
        echo color(" ✓ 日志已清空\n", '32');
    } else {
        echo " 日志文件不存在\n";
    }
    exit(0);
}

if (isset($opts['stats'])) {
    show_output_stats();
    show_stats();
    exit(0);
}

$lines = isset($opts['lines']) ? (int)$opts['lines'] : 50;

if (isset($opts['tail'])) {
    // 持续监控模式
    echo "\033[?25l";  // 隐藏光标
    while (true) {
        show_header();
        show_output_stats();
        show_logs($lines);
        echo color(" [自动刷新 每 " . REFRESH_SEC . "s | Ctrl+C 退出]\n", '90');
        sleep(REFRESH_SEC);
    }
} else {
    // 单次显示
    show_output_stats();
    show_logs($lines);
}
