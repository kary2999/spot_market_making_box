<?php
/**
 * 现货铺单配置生成器 (PHP 7.3+)
 *
 * 规则：
 *   - 9 档位，覆盖当前价 ±50%
 *   - 近盘（dom 1-2）：占据前 100 个价格的 80%-100%
 *   - 近盘挂单量：对标交易对深度均量
 *   - 中盘+远盘（dom 3-9）：均分剩余价格区间和挂单量
 *
 * 用法:
 *   php generate_box_config.php --symbol trx_usdt --pid 3 --levels 9 \
 *       --total_usdt 2000000 --depth_ratio 0.3
 */

bcscale(20);

define('BINANCE_BASE_URL', 'https://api.binance.com');
define('REQUEST_TIMEOUT', 10);

// 近盘覆盖的 tick 数
define('NEAR_TICKS', 100);

// 近盘档位数（levels>6 时 2 档，否则 1 档）
// 盘口取深度档位（用于计算 number_float）
define('DEPTH_NEAR', 5);
define('DEPTH_OTHER', 20);

// ==================== 币安 API ====================

function normalize_symbol($symbol)
{
    return strtoupper(str_replace('_', '', $symbol));
}

function binance_get($path, $params = array())
{
    $url = BINANCE_BASE_URL . $path;
    if (!empty($params)) {
        $url .= '?' . http_build_query($params);
    }

    $ch = curl_init($url);
    curl_setopt_array($ch, array(
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT        => REQUEST_TIMEOUT,
        CURLOPT_SSL_VERIFYPEER => true,
        CURLOPT_HTTPHEADER     => array('Accept: application/json'),
    ));

    $response = curl_exec($ch);
    $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $error    = curl_error($ch);
    curl_close($ch);

    if ($response === false) {
        throw new RuntimeException("币安 API 请求失败: " . $error);
    }
    if ($httpCode !== 200) {
        throw new RuntimeException("币安 API 请求失败: HTTP {$httpCode} - {$response}");
    }

    return json_decode($response, true);
}

function get_price($symbol)
{
    $data = binance_get('/api/v3/ticker/price', array('symbol' => normalize_symbol($symbol)));
    return $data['price'];
}

function get_exchange_info($symbol)
{
    $data    = binance_get('/api/v3/exchangeInfo', array('symbol' => normalize_symbol($symbol)));
    $symbols = isset($data['symbols']) ? $data['symbols'] : array();

    if (empty($symbols)) {
        throw new RuntimeException("未找到交易对信息: {$symbol}");
    }

    $filters = array();
    foreach ($symbols[0]['filters'] as $f) {
        $filters[$f['filterType']] = $f;
    }

    $tickSize = isset($filters['PRICE_FILTER']['tickSize']) ? $filters['PRICE_FILTER']['tickSize'] : null;
    $stepSize = isset($filters['LOT_SIZE']['stepSize']) ? $filters['LOT_SIZE']['stepSize'] : null;

    if (!$tickSize || !$stepSize) {
        throw new RuntimeException("未找到精度信息: {$symbol}");
    }

    return array('tickSize' => $tickSize, 'stepSize' => $stepSize);
}

function get_order_book($symbol, $limit = 20)
{
    return binance_get('/api/v3/depth', array(
        'symbol' => normalize_symbol($symbol),
        'limit'  => $limit,
    ));
}

// ==================== 工具 ====================

function decimal_places($tickStr)
{
    $tickStr = rtrim(rtrim($tickStr, '0'), '.');
    $pos = strpos($tickStr, '.');
    return $pos === false ? 0 : strlen($tickStr) - $pos - 1;
}

function format_qty($value, $stepSize)
{
    $places = decimal_places($stepSize);
    $factor = bcpow('10', (string)$places);
    return bcdiv(bcmul($value, $factor, 0), $factor, $places);
}

/**
 * 计算盘口深度均量
 * 取买卖双侧前 depth 档的累计量均值
 */
function calc_depth_avg_qty($orderBook, $depth)
{
    $bids = isset($orderBook['bids']) ? $orderBook['bids'] : array();
    $asks = isset($orderBook['asks']) ? $orderBook['asks'] : array();

    $bidTotal = '0';
    $askTotal = '0';
    for ($i = 0; $i < min($depth, count($bids)); $i++) {
        $bidTotal = bcadd($bidTotal, $bids[$i][1]);
    }
    for ($i = 0; $i < min($depth, count($asks)); $i++) {
        $askTotal = bcadd($askTotal, $asks[$i][1]);
    }

    return bcdiv(bcadd($bidTotal, $askTotal), '2', 10);
}

/**
 * 生成 number_float 区间字符串
 */
function make_number_float($avgQty, $stepSize)
{
    $base = bcmul($avgQty, '0.2', 20);
    if (bccomp($base, $stepSize) < 0) {
        $base = $stepSize;
    }

    $qtyMin = format_qty(bcmul($base, '0.5', 20), $stepSize);
    $qtyMax = format_qty($base, $stepSize);

    if ($qtyMin === $qtyMax) {
        $qtyMin = format_qty($stepSize, $stepSize);
    }

    return $qtyMin . '-' . $qtyMax;
}

// ==================== 核心：价格区间计算 ====================

/**
 * 计算各档位价格百分比区间
 *
 * 规则：
 *   总范围 = ±50%（卖方 100%~150%，买方 50%~100%）
 *   近盘（dom 1~nearLevels）= 前 NEAR_TICKS 个 tick，均分
 *   剩余档位 = 均分剩余区间
 */
function build_price_ranges($currentPrice, $tickSize, $levels, $direction, $nearLevels)
{
    // 近盘百分比宽度 = NEAR_TICKS × tickSize / currentPrice × 100
    $nearOffset = bcmul((string)NEAR_TICKS, $tickSize, 20);
    $nearPctWidth = bcdiv(bcmul($nearOffset, '100', 10), $currentPrice, 10);

    // 总范围 50%
    $totalPctWidth = '50';

    // 剩余范围 = 50% - 近盘宽度
    $remainPctWidth = bcsub($totalPctWidth, $nearPctWidth, 10);
    if (bccomp($remainPctWidth, '0', 10) <= 0) {
        $remainPctWidth = '0.001';
    }

    // 剩余档位数
    $remainLevels = $levels - $nearLevels;

    // 每档宽度
    $nearPerDom   = bcdiv($nearPctWidth, (string)$nearLevels, 10);
    $remainPerDom = $remainLevels > 0 ? bcdiv($remainPctWidth, (string)$remainLevels, 10) : '0';

    $ranges    = array();
    $cursorPct = '100';

    for ($dom = 1; $dom <= $levels; $dom++) {
        $isNear = ($dom <= $nearLevels);
        $widthPct = $isNear ? $nearPerDom : $remainPerDom;
        $isLast = ($dom === $levels);

        if ($direction === -1) {
            // 卖方：100% → 150%
            $lowPct  = $cursorPct;
            $highPct = $isLast ? '150' : bcadd($cursorPct, $widthPct, 10);
            $ranges[] = array($lowPct, $highPct);
            $cursorPct = $highPct;
        } else {
            // 买方：100% → 50%
            $highPct = $cursorPct;
            $lowPct  = $isLast ? '50' : bcsub($cursorPct, $widthPct, 10);
            $ranges[] = array($lowPct, $highPct);
            $cursorPct = $lowPct;
        }
    }

    return $ranges;
}

// ==================== 配置生成 ====================

function generate_configs($symbol, $levels, $totalUsdt, $pid, $currentPrice, $exchangeInfo, $orderBook)
{
    $tickSize = $exchangeInfo['tickSize'];
    $stepSize = $exchangeInfo['stepSize'];

    // 近盘档位数
    $nearLevels = ($levels > 6) ? 2 : 1;
    $remainLevels = $levels - $nearLevels;

    // 总委托笔数
    $totalTrust = 1000;

    // 近盘挂单量 = 对标深度均量
    $nearDepthQty  = calc_depth_avg_qty($orderBook, DEPTH_NEAR);
    $otherDepthQty = calc_depth_avg_qty($orderBook, DEPTH_OTHER);

    $nearNumberFloat  = make_number_float($nearDepthQty, $stepSize);
    $otherNumberFloat = make_number_float($otherDepthQty, $stepSize);

    // 近盘 trust_num：总量的 15%，均分给近盘档位
    $nearTrustTotal = max(1, (int)round($totalTrust * 0.15));
    $nearTrustPerDom = max(1, (int)round($nearTrustTotal / $nearLevels));

    // 剩余 trust_num：均分给中远盘
    $remainTrustTotal = $totalTrust - $nearTrustTotal;
    $remainTrustPerDom = $remainLevels > 0 ? max(1, (int)round($remainTrustTotal / $remainLevels)) : 0;

    $configs = array();

    foreach (array(-1, 1) as $direction) {
        $priceRanges = build_price_ranges($currentPrice, $tickSize, $levels, $direction, $nearLevels);

        for ($dom = 1; $dom <= $levels; $dom++) {
            $isNear = ($dom <= $nearLevels);

            $lowPct  = $priceRanges[$dom - 1][0];
            $highPct = $priceRanges[$dom - 1][1];
            $priceFloat = bcadd($lowPct, '0', 3) . '-' . bcadd($highPct, '0', 3);

            $configs[] = array(
                'box_id'                => null,
                'pid'                   => $pid,
                'direction'             => $direction,
                'dom'                   => $dom,
                'trust_num'             => $isNear ? $nearTrustPerDom : $remainTrustPerDom,
                'price_float'           => $priceFloat,
                'number_float'          => $isNear ? $nearNumberFloat : $otherNumberFloat,
                'change_trust_num'      => $isNear ? 0 : 1,
                'change_number_float'   => $isNear ? $nearNumberFloat : $otherNumberFloat,
                'change_survival_time'  => $isNear ? '3-10' : '10-30',
                'status'                => 1,
                '_symbol'               => $symbol,
                '_zone'                 => $isNear ? 'near' : 'other',
                '_direction_label'      => $direction === -1 ? '卖' : '买',
            );
        }
    }

    return $configs;
}

// ==================== SQL 输出 ====================

function generate_sql($configs, $outputPath)
{
    $dir = dirname($outputPath);
    if (!is_dir($dir)) {
        mkdir($dir, 0755, true);
    }

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
         . implode(",\n", $rows) . ";\n";

    file_put_contents($outputPath, $sql);
    echo "[输出] SQL 文件已生成: {$outputPath}\n";
}

// ==================== 控制台输出 ====================

function pct_to_actual($priceFloatPct, $refPrice)
{
    $parts = explode('-', $priceFloatPct);
    $low  = bcdiv(bcmul($refPrice, $parts[0], 10), '100', 6);
    $high = bcdiv(bcmul($refPrice, $parts[1], 10), '100', 6);
    return $low . ' ~ ' . $high;
}

function pct_width($priceFloatPct)
{
    $parts = explode('-', $priceFloatPct);
    return bcsub($parts[1], $parts[0], 3);
}

function ticks_count($priceFloatPct, $refPrice, $tickSize)
{
    $parts = explode('-', $priceFloatPct);
    $low  = bcdiv(bcmul($refPrice, $parts[0], 10), '100', 10);
    $high = bcdiv(bcmul($refPrice, $parts[1], 10), '100', 10);
    $diff = bcsub($high, $low, 10);
    if (bccomp($diff, '0', 10) < 0) {
        $diff = bcmul($diff, '-1', 10);
    }
    return (int)bcdiv($diff, $tickSize, 0);
}

function print_output($configs, $levels, $currentPrice, $tickSize, $symbol, $pid, $totalUsdt, $depthRatio)
{
    $nearOffset = bcmul((string)NEAR_TICKS, $tickSize, 10);
    $nearPct    = bcdiv(bcmul($nearOffset, '100', 10), $currentPrice, 4);
    $symbolDisplay = strtoupper(str_replace('_', '/', $symbol));
    $pricePlaces   = decimal_places($tickSize);

    // 标题
    $sep = str_repeat('-', 70);
    echo "\n{$sep}\n";
    echo "  交易对   : {$symbolDisplay}  (当前价: {$currentPrice})\n";
    echo "  tickSize : {$tickSize} ({$pricePlaces}位)   近盘: " . NEAR_TICKS . " ticks = {$nearOffset} ({$nearPct}%)\n";
    echo sprintf("  pid: %d   levels: %d   total: %s USDT   depth_ratio: %.1f\n", $pid, $levels, number_format($totalUsdt, 0), $depthRatio);
    echo "{$sep}\n\n";

    // 分卖买
    $sellMap = array();
    $buyMap  = array();
    foreach ($configs as $c) {
        if ($c['direction'] === -1) {
            $sellMap[$c['dom']] = $c;
        } else {
            $buyMap[$c['dom']] = $c;
        }
    }

    // 表格
    echo sprintf(" %-3s %-6s %6s %6s %6s  %-22s  %-22s  %-16s\n",
        'dom', '区域', '笔数', 'ticks', '宽度%', '卖价区间', '买价区间', '数量区间');
    echo str_repeat('-', 105) . "\n";

    $zoneCn = array('near' => '近盘', 'other' => '均分');

    for ($dom = 1; $dom <= $levels; $dom++) {
        $sc = isset($sellMap[$dom]) ? $sellMap[$dom] : array();
        $bc = isset($buyMap[$dom]) ? $buyMap[$dom] : array();

        $zone      = isset($sc['_zone']) ? $sc['_zone'] : '';
        $zoneLabel = isset($zoneCn[$zone]) ? $zoneCn[$zone] : '';
        $trustNum  = isset($sc['trust_num']) ? $sc['trust_num'] : '-';
        $sellPf    = isset($sc['price_float']) ? $sc['price_float'] : '-';
        $buyPf     = isset($bc['price_float']) ? $bc['price_float'] : '-';
        $numFloat  = isset($sc['number_float']) ? $sc['number_float'] : '-';
        $ticks     = $sellPf !== '-' ? ticks_count($sellPf, $currentPrice, $tickSize) : '-';
        $width     = $sellPf !== '-' ? pct_width($sellPf) : '-';

        echo sprintf(" %-3d %-6s %6s %6s %6s  %-22s  %-22s  %-16s\n",
            $dom, $zoneLabel, $trustNum, $ticks, $width, $sellPf, $buyPf, $numFloat);
    }
    echo "\n";

    // 实际价格明细
    echo " 实际价格对照:\n";
    echo str_repeat('-', 70) . "\n";
    for ($dom = 1; $dom <= $levels; $dom++) {
        $sc = isset($sellMap[$dom]) ? $sellMap[$dom] : array();
        $bc = isset($buyMap[$dom]) ? $buyMap[$dom] : array();
        $sellActual = isset($sc['price_float']) ? pct_to_actual($sc['price_float'], $currentPrice) : '-';
        $buyActual  = isset($bc['price_float']) ? pct_to_actual($bc['price_float'], $currentPrice) : '-';
        echo sprintf(" dom%-2d  卖: %-28s  买: %-28s\n", $dom, $sellActual, $buyActual);
    }
    echo "\n共 " . count($configs) . " 条配置\n\n";
}

// ==================== CLI ====================

function parse_args()
{
    $opts = getopt('', array(
        'symbol:', 'pid:', 'levels:', 'total_usdt:', 'depth_ratio:', 'output_dir:',
    ));

    if (empty($opts['symbol']) || !isset($opts['pid'])) {
        echo "用法: php generate_box_config.php --symbol trx_usdt --pid 3 --levels 9 --total_usdt 2000000 --depth_ratio 0.3\n";
        exit(1);
    }

    return array(
        'symbol'      => strtolower($opts['symbol']),
        'pid'         => (int)$opts['pid'],
        'levels'      => isset($opts['levels']) ? (int)$opts['levels'] : 9,
        'total_usdt'  => isset($opts['total_usdt']) ? (float)$opts['total_usdt'] : 1000000.0,
        'depth_ratio' => isset($opts['depth_ratio']) ? (float)$opts['depth_ratio'] : 0.2,
        'output_dir'  => isset($opts['output_dir']) ? $opts['output_dir'] : 'output',
    );
}

function main()
{
    $args = parse_args();

    echo "[API] 正在获取 " . strtoupper($args['symbol']) . " 行情数据...\n";

    try {
        $currentPrice = get_price($args['symbol']);
        $exchangeInfo = get_exchange_info($args['symbol']);
        $orderBook    = get_order_book($args['symbol'], 20);
    } catch (Exception $e) {
        fwrite(STDERR, "[错误] " . $e->getMessage() . "\n");
        exit(1);
    }

    echo "[API] 价格: {$currentPrice}  tickSize: {$exchangeInfo['tickSize']}  stepSize: {$exchangeInfo['stepSize']}\n";

    $configs = generate_configs(
        $args['symbol'],
        $args['levels'],
        $args['total_usdt'],
        $args['pid'],
        $currentPrice,
        $exchangeInfo,
        $orderBook
    );

    print_output($configs, $args['levels'], $currentPrice, $exchangeInfo['tickSize'],
        $args['symbol'], $args['pid'], $args['total_usdt'], $args['depth_ratio']);

    $safeSymbol = str_replace('/', '_', $args['symbol']);
    $sqlPath = $args['output_dir'] . '/' . $safeSymbol . '_pid' . $args['pid'] . '.sql';
    generate_sql($configs, $sqlPath);
}

main();
