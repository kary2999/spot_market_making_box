<?php
/**
 * 小聋女行为日志工具
 *
 * 用法（命令行）:
 *   php ai_log.php CMD "执行命令" "详情"
 *   php ai_log.php FILE "读取文件 /path/to/file"
 *   php ai_log.php HTTP "GET https://api.binance.com/..."
 *   php ai_log.php GIT "git commit -m '...'"
 *   php ai_log.php MSG "发送消息给父亲大人"
 *   php ai_log.php THINK "正在分析..."
 *
 * 类型: CMD FILE HTTP GIT MSG THINK
 */

define('AI_ACT_LOG', __DIR__ . '/logs/ai_activity.log');
define('LOG_MAX',    1000);

function ai_log($type, $what, $detail = '')
{
    $dir = dirname(AI_ACT_LOG);
    if (!is_dir($dir)) mkdir($dir, 0755, true);

    $entry = json_encode([
        'time'   => date('Y-m-d H:i:s'),
        'ts'     => time(),
        'type'   => strtoupper($type),
        'what'   => $what,
        'detail' => $detail,
    ], JSON_UNESCAPED_UNICODE) . "\n";

    file_put_contents(AI_ACT_LOG, $entry, FILE_APPEND | LOCK_EX);

    $lines = file(AI_ACT_LOG);
    if (count($lines) > LOG_MAX) {
        file_put_contents(AI_ACT_LOG, implode('', array_slice($lines, -LOG_MAX)));
    }
}

// CLI 调用
if (php_sapi_name() === 'cli' && isset($argv[1])) {
    $type   = $argv[1] ?? 'CMD';
    $what   = $argv[2] ?? '';
    $detail = $argv[3] ?? '';
    ai_log($type, $what, $detail);
}
