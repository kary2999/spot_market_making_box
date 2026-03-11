<?php
/**
 * 批量铺单配置生成器
 *
 * 用法:
 *   php batch_generate.php [--ini symbol.ini] [--dry-run]
 *
 * 读取 symbol.ini，批量生成所有交易对的铺单 SQL
 * 汇总输出到 output/batch_all.sql
 */

require_once __DIR__ . '/generate_box_config.php';

// ==================== INI 解析 ====================

function parse_ini_file_custom($path)
{
    if (!file_exists($path)) {
        throw new RuntimeException("配置文件不存在: {$path}");
    }

    $result = array('config' => array(), 'symbols' => array());
    $section = '';

    foreach (file($path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
        $line = trim($line);
        if ($line === '' || $line[0] === ';' || $line[0] === '#') {
            continue;
        }
        if (preg_match('/^\[(.+)\]$/', $line, $m)) {
            $section = strtolower(trim($m[1]));
            continue;
        }
        if (strpos($line, '=') !== false) {
            list($k, $v) = explode('=', $line, 2);
            $k = trim($k);
            $v = trim($v);
            if ($section === 'config') {
                $result['config'][$k] = $v;
            } elseif ($section === 'symbols') {
                $result['symbols'][$k] = $v;  // pid => symbol
            }
        }
    }

    return $result;
}

// ==================== 批量主函数 ====================

function batch_main()
{
    $opts = getopt('', array('ini:', 'dry-run'));
    $iniPath = isset($opts['ini']) ? $opts['ini'] : __DIR__ . '/symbol.ini';
    $dryRun  = isset($opts['dry-run']);

    echo "\n========================================\n";
    echo " 批量铺单配置生成器\n";
    echo "========================================\n";
    echo " 配置文件: {$iniPath}\n";
    if ($dryRun) {
        echo " [DRY-RUN 模式：不写文件]\n";
    }
    echo "\n";

    $ini = parse_ini_file_custom($iniPath);
    $cfg = $ini['config'];

    $levels     = isset($cfg['levels'])      ? (int)$cfg['levels']           : 9;
    $totalUsdt  = isset($cfg['total_usdt'])  ? (float)$cfg['total_usdt']     : 1000000.0;
    $depthRatio = isset($cfg['depth_ratio']) ? (float)$cfg['depth_ratio']    : 0.2;
    $totalTrust = isset($cfg['total_trust']) ? (int)$cfg['total_trust']      : 800;
    $outputDir  = isset($cfg['output_dir'])  ? $cfg['output_dir']            : 'output';

    if (!is_dir($outputDir)) {
        mkdir($outputDir, 0755, true);
    }

    $symbols = $ini['symbols'];
    $total   = count($symbols);
    $success = 0;
    $failed  = array();

    // 批量 SQL 汇总
    $batchSqlPath = $outputDir . '/batch_all.sql';
    $batchSql     = "-- 批量铺单配置 生成时间: " . date('Y-m-d H:i:s') . "\n";
    $batchSql    .= "-- 共 {$total} 个交易对\n\n";

    echo sprintf(" %-6s %-20s %-10s %-8s %s\n", 'PID', '交易对', '状态', '耗时(s)', '说明');
    echo str_repeat('-', 70) . "\n";

    foreach ($symbols as $pid => $symbol) {
        $pid    = (int)$pid;
        $symbol = strtolower(trim($symbol));
        $start  = microtime(true);

        try {
            // 1. 本所精度
            $localInfo = get_local_exchange_info($symbol);

            // 2. 行情数据（币安→Gate→KuCoin→Bitget）
            $marketData   = get_market_data($symbol, 20);
            $currentPrice = $marketData['price'];
            $orderBook    = $marketData['orderBook'];
            $source       = $marketData['source'];

            // 3. 生成配置
            $configs = generate_configs(
                $symbol, $levels, $totalUsdt, $pid,
                $currentPrice, $localInfo, $orderBook, $totalTrust
            );

            // 4. 生成 SQL 内容
            $sqlContent = build_sql_content($configs);

            // 5. 写单个文件
            if (!$dryRun) {
                $singlePath = $outputDir . '/' . $symbol . '_pid' . $pid . '.sql';
                file_put_contents($singlePath, $sqlContent);
                $batchSql .= "-- [{$pid}] {$symbol}\n" . $sqlContent . "\n";
            }

            $elapsed = round(microtime(true) - $start, 2);
            printf(" %-6d %-20s %-10s %-8s [%s] 价格:%s 近盘:%dticks\n",
                $pid,
                strtoupper($symbol),
                '✓ 成功',
                $elapsed,
                $source,
                $currentPrice,
                calc_near_ticks($currentPrice, $localInfo['tickSize'])
            );
            $success++;

        } catch (Exception $e) {
            $elapsed = round(microtime(true) - $start, 2);
            printf(" %-6d %-20s %-10s %-8s %s\n",
                $pid,
                strtoupper($symbol),
                '✗ 失败',
                $elapsed,
                $e->getMessage()
            );
            $failed[] = array('pid' => $pid, 'symbol' => $symbol, 'error' => $e->getMessage());
        }

        // 避免触发 API 限速
        usleep(200000);  // 200ms
    }

    // 写批量汇总文件
    if (!$dryRun && $success > 0) {
        file_put_contents($batchSqlPath, $batchSql);
    }

    // 汇总
    echo str_repeat('=', 70) . "\n";
    echo sprintf(" 完成: %d/%d  失败: %d\n", $success, $total, count($failed));
    if (!$dryRun && $success > 0) {
        echo " 汇总 SQL: {$batchSqlPath}\n";
        echo " 单个 SQL: {$outputDir}/<symbol>_pid<pid>.sql\n";
    }
    if (!empty($failed)) {
        echo "\n 失败列表:\n";
        foreach ($failed as $f) {
            echo "   pid={$f['pid']} {$f['symbol']}: {$f['error']}\n";
        }
    }
    echo "\n";
}

/**
 * 从 generate_configs 结果构建 SQL 字符串（不写文件）
 */
function build_sql_content($configs)
{
    $fields = array(
        'box_id', 'pid', 'direction', 'dom', 'trust_num',
        'price_float', 'number_float', 'change_trust_num',
        'change_number_float', 'change_survival_time', 'status',
    );
    $strFields = array('price_float', 'number_float', 'change_number_float', 'change_survival_time');

    $rows = array();
    foreach ($configs as $c) {
        $parts = array();
        foreach ($fields as $f) {
            $v = $c[$f];
            if ($v === null) {
                $parts[] = 'null';
            } elseif (in_array($f, $strFields)) {
                $parts[] = "'" . preg_replace('/[^0-9.\-]/', '', (string)$v) . "'";
            } else {
                $parts[] = (string)(int)$v;
            }
        }
        $rows[] = '  (' . implode(', ', $parts) . ')';
    }

    $sql = "INSERT INTO spot_market_making_box (" . implode(', ', $fields) . ")\nVALUES\n"
         . implode(",\n", $rows) . ";\n\n";

    // UPDATE 语句
    $sql .= "-- UPDATE\n";
    foreach ($configs as $c) {
        $sets = array();
        foreach ($fields as $f) {
            if (in_array($f, array('box_id', 'pid', 'direction', 'dom'))) continue;
            $v = $c[$f];
            if ($v === null) {
                $sets[] = "{$f} = null";
            } elseif (in_array($f, $strFields)) {
                $sets[] = "{$f} = '" . preg_replace('/[^0-9.\-]/', '', (string)$v) . "'";
            } else {
                $sets[] = "{$f} = " . (int)$v;
            }
        }
        $sql .= "UPDATE spot_market_making_box SET " . implode(', ', $sets)
              . " WHERE pid = {$c['pid']} AND direction = {$c['direction']} AND dom = {$c['dom']};\n";
    }

    return $sql . "\n";
}

batch_main();
