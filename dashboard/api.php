<?php
header('Content-Type: application/json; charset=utf-8');
header('Access-Control-Allow-Origin: *');
header('Cache-Control: no-cache');

define('BASE_DIR',   dirname(__DIR__));
define('LOG_FILE',   BASE_DIR . '/logs/operations.log');
define('OUTPUT_DIR', BASE_DIR . '/output');
define('AI_LOG',     BASE_DIR . '/logs/ai_cost.json');
define('RUN_LOG',    BASE_DIR . '/logs/run_output.log');
define('PID_FILE',   BASE_DIR . '/logs/run.pid');

$action = isset($_GET['action']) ? $_GET['action'] : 'stats';

// ────────────────────────────────────────────
if ($action === 'stats') {
    $sqlFiles  = glob(OUTPUT_DIR . '/*.sql') ?: [];
    $batchFile = OUTPUT_DIR . '/batch_all.sql';
    $batchSize = file_exists($batchFile) ? round(filesize($batchFile)/1024, 1) : 0;

    $apiOk = $apiFail = $sqlWrites = $batchRuns = 0;
    $symbolsDone = [];
    if (file_exists(LOG_FILE)) {
        foreach (file(LOG_FILE, FILE_IGNORE_NEW_LINES|FILE_SKIP_EMPTY_LINES) as $line) {
            $d = json_decode($line, true);
            if (!$d) continue;
            if ($d['action'] === 'API_MARKET') {
                $d['status'] === 'OK' ? $apiOk++ : $apiFail++;
            }
            if ($d['action'] === 'SQL_WRITE') {
                $sqlWrites++;
                if (preg_match('/(\w+_usdt)_pid/i', $d['detail'], $m))
                    $symbolsDone[] = strtoupper($m[1]);
            }
            if ($d['action'] === 'BATCH_START') $batchRuns++;
        }
    }

    $ai = ['tokens_in'=>0,'tokens_out'=>0,'cost_usd'=>0,'model'=>'','updated_at'=>''];
    if (file_exists(AI_LOG)) $ai = array_merge($ai, json_decode(file_get_contents(AI_LOG), true) ?: []);

    // 是否有任务在跑
    $running = false;
    if (file_exists(PID_FILE)) {
        $pid = trim(file_get_contents(PID_FILE));
        $running = $pid && file_exists("/proc/{$pid}");
    }

    echo json_encode([
        'sql_files'    => count($sqlFiles),
        'batch_size'   => $batchSize,
        'api_ok'       => $apiOk,
        'api_fail'     => $apiFail,
        'sql_writes'   => $sqlWrites,
        'batch_runs'   => $batchRuns,
        'symbols_done' => count(array_unique($symbolsDone)),
        'ai'           => $ai,
        'running'      => $running,
        'server_time'  => date('Y-m-d H:i:s'),
    ]);
}

// ────────────────────────────────────────────
elseif ($action === 'logs') {
    $limit = isset($_GET['limit']) ? (int)$_GET['limit'] : 100;
    $since = isset($_GET['since']) ? (int)$_GET['since'] : 0;
    if (!file_exists(LOG_FILE)) { echo json_encode(['logs'=>[],'total'=>0]); exit; }
    $lines = file(LOG_FILE, FILE_IGNORE_NEW_LINES|FILE_SKIP_EMPTY_LINES);
    $logs  = [];
    foreach (array_slice($lines, -$limit) as $line) {
        $d = json_decode($line, true);
        if ($d && $d['ts'] > $since) $logs[] = $d;
    }
    echo json_encode(['logs'=>$logs, 'total'=>count($lines)]);
}

// ────────────────────────────────────────────
elseif ($action === 'run') {
    // 检查是否已在运行
    if (file_exists(PID_FILE)) {
        $pid = trim(file_get_contents(PID_FILE));
        if ($pid && file_exists("/proc/{$pid}")) {
            echo json_encode(['ok'=>false,'msg'=>'任务正在运行中，请稍候']);
            exit;
        }
    }
    // 清空旧输出
    @file_put_contents(RUN_LOG, "");

    $php    = '/usr/bin/php8.3';
    $script = BASE_DIR . '/batch_generate.php';
    $ini    = isset($_GET['ini']) ? escapeshellarg($_GET['ini']) : escapeshellarg(BASE_DIR . '/symbol.ini');
    $cmd    = "{$php} {$script} --ini {$ini} > " . escapeshellarg(RUN_LOG) . " 2>&1 & echo $!";
    $pid    = trim(shell_exec($cmd));
    file_put_contents(PID_FILE, $pid);
    echo json_encode(['ok'=>true,'pid'=>$pid,'msg'=>'批量任务已启动']);
}

// ────────────────────────────────────────────
elseif ($action === 'output') {
    // 返回运行输出（分页）
    $offset = isset($_GET['offset']) ? (int)$_GET['offset'] : 0;
    $text   = file_exists(RUN_LOG) ? file_get_contents(RUN_LOG) : '';
    $chunk  = substr($text, $offset);

    $running = false;
    if (file_exists(PID_FILE)) {
        $pid = trim(file_get_contents(PID_FILE));
        $running = $pid && file_exists("/proc/{$pid}");
    }

    echo json_encode([
        'text'    => $chunk,
        'offset'  => $offset + strlen($chunk),
        'running' => $running,
        'done'    => !$running && strlen($text) > 0,
    ]);
}

// ────────────────────────────────────────────
elseif ($action === 'ai_update') {
    $dir = dirname(AI_LOG);
    if (!is_dir($dir)) mkdir($dir, 0755, true);
    file_put_contents(AI_LOG, json_encode([
        'tokens_in'  => (int)($_GET['in']   ?? 0),
        'tokens_out' => (int)($_GET['out']  ?? 0),
        'cost_usd'   => (float)($_GET['cost'] ?? 0),
        'model'      => $_GET['model'] ?? '',
        'updated_at' => date('Y-m-d H:i:s'),
    ]));
    echo json_encode(['ok'=>true]);
}
