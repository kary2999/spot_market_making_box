<?php
header('Content-Type: application/json; charset=utf-8');
header('Access-Control-Allow-Origin: *');

define('LOG_FILE',   dirname(__DIR__) . '/logs/operations.log');
define('OUTPUT_DIR', dirname(__DIR__) . '/output');
define('AI_LOG',     dirname(__DIR__) . '/logs/ai_cost.json');

$action = isset($_GET['action']) ? $_GET['action'] : 'logs';

if ($action === 'logs') {
    $limit = isset($_GET['limit']) ? (int)$_GET['limit'] : 100;
    $since = isset($_GET['since']) ? (int)$_GET['since'] : 0;

    if (!file_exists(LOG_FILE)) {
        echo json_encode(array('logs' => array(), 'total' => 0));
        exit;
    }

    $lines = file(LOG_FILE, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
    $logs  = array();
    foreach (array_slice($lines, -$limit) as $line) {
        $d = json_decode($line, true);
        if ($d && $d['ts'] > $since) {
            $logs[] = $d;
        }
    }
    echo json_encode(array('logs' => $logs, 'total' => count($lines)));

} elseif ($action === 'stats') {
    // 输出文件统计
    $sqlFiles  = glob(OUTPUT_DIR . '/*.sql');
    $batchFile = OUTPUT_DIR . '/batch_all.sql';
    $batchSize = file_exists($batchFile) ? round(filesize($batchFile) / 1024, 1) : 0;

    // 日志统计
    $apiOk = $apiFail = $sqlWrites = $batchRuns = 0;
    $symbolsDone = array();
    if (file_exists(LOG_FILE)) {
        foreach (file(LOG_FILE, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
            $d = json_decode($line, true);
            if (!$d) continue;
            if ($d['action'] === 'API_MARKET') {
                if ($d['status'] === 'OK')   $apiOk++;
                if ($d['status'] === 'FAIL') $apiFail++;
            }
            if ($d['action'] === 'SQL_WRITE') {
                $sqlWrites++;
                if (preg_match('/(\w+_usdt)_pid/i', $d['detail'], $m)) {
                    $symbolsDone[] = strtoupper($m[1]);
                }
            }
            if ($d['action'] === 'BATCH_START') $batchRuns++;
        }
    }

    // AI 费用
    $aiCost = array('tokens_in' => 0, 'tokens_out' => 0, 'cost_usd' => 0);
    if (file_exists(AI_LOG)) {
        $aiCost = json_decode(file_get_contents(AI_LOG), true) ?: $aiCost;
    }

    echo json_encode(array(
        'sql_files'    => count($sqlFiles),
        'batch_size'   => $batchSize,
        'api_ok'       => $apiOk,
        'api_fail'     => $apiFail,
        'sql_writes'   => $sqlWrites,
        'batch_runs'   => $batchRuns,
        'symbols_done' => count(array_unique($symbolsDone)),
        'ai'           => $aiCost,
        'server_time'  => date('Y-m-d H:i:s'),
    ));
} elseif ($action === 'ai_update') {
    // AI 费用更新（由 OpenClaw 调用）
    $in      = isset($_GET['in'])   ? (int)$_GET['in']       : 0;
    $out     = isset($_GET['out'])  ? (int)$_GET['out']      : 0;
    $cost    = isset($_GET['cost']) ? (float)$_GET['cost']   : 0;
    $model   = isset($_GET['model']) ? $_GET['model']        : '';
    $dir = dirname(AI_LOG);
    if (!is_dir($dir)) mkdir($dir, 0755, true);
    file_put_contents(AI_LOG, json_encode(array(
        'tokens_in'  => $in,
        'tokens_out' => $out,
        'cost_usd'   => $cost,
        'model'      => $model,
        'updated_at' => date('Y-m-d H:i:s'),
    )));
    echo json_encode(array('ok' => true));
}
