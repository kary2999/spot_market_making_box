<?php
/**
 * 现货铺单配置生成器 (PHP 7.3+)
 *
 * 数据源：
 *   - 本所 exchangeInfo：价格精度(price_precision)、数量精度、最小挂单量
 *   - 币安：参考价格、盘口深度
 *
 * 规则：
 *   - 9 档位，覆盖当前价 ±50%
 *   - 近盘（dom 1-2）：每档覆盖 100 个价格位，填充率 ≥ 0.85
 *   - 近盘挂单量：对标币安深度均量
 *   - 中远盘（dom 3-9）：均分剩余价格区间和挂单量
 *
 * 用法:
 *   php generate_box_config.php --symbol trx_usdt --pid 3 --levels 9 \
 *       --total_usdt 2000000 --depth_ratio 0.3
 */

bcscale(20);

define('BINANCE_BASE_URL', 'https://api.binance.com');
define('EXCHANGE_INFO_URL', 'https://app.nn88zl.com/spot/read/pub/exchangeInfo?app_id=AwyOTFRlsfQ5mRkqwCNaEd5T');
define('REQUEST_TIMEOUT', 10);

// 近盘每档覆盖的价格位数
define('NEAR_TICKS_PER_DOM', 100);

// 近盘填充率：trust_num / ticks >= 0.85
define('NEAR_FILL_RATE', 0.85);

// 盘口取深度档位（用于计算 number_float）
define('DEPTH_NEAR', 5);
define('DEPTH_OTHER', 20);

// ==================== HTTP 请求 ====================

function http_get($url)
{
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
        throw new RuntimeException("HTTP 请求失败: " . $error);
    }
    if ($httpCode !== 200) {
        throw new RuntimeException("HTTP {$httpCode}: {$response}");
    }

    return json_decode($response, true);
}

// ==================== 本所 API ====================

/**
 * 从本所 exchangeInfo 获取交易对精度信息
 */
function get_local_exchange_info($symbol)
{
    $data = http_get(EXCHANGE_INFO_URL);

    if (!isset($data['data']['symbols'])) {
        throw new RuntimeException("本所 exchangeInfo 返回格式异常");
    }

    foreach ($data['data']['symbols'] as $s) {
        if ($s['name'] === $symbol) {
            $pricePrecision  = (int)$s['price_precision'];
            $numberPrecision = (int)$s['number_precision'];
            $tickSize = bcpow('0.1', (string)$pricePrecision, $pricePrecision);
            $stepSize = bcpow('0.1', (string)$numberPrecision, $numberPrecision);

            return array(
                'symbol_id'        => $s['symbol_id'],
                'price_precision'  => $pricePrecision,
                'number_precision' => $numberPrecision,
                'tickSize'         => $tickSize,
                'stepSize'         => $stepSize,
                'min_trade'        => $s['min_trade'],
                'max_trade'        => $s['max_trade'],
                'display'          => $s['display'],
            );
        }
    }

    // 列出可用交易对
    $available = array();
    foreach ($data['data']['symbols'] as $s) {
        if ($s['status'] == 1) {
            $available[] = $s['name'];
        }
    }
    throw new RuntimeException("本所未找到交易对: {$symbol}\n可用: " . implode(', ', $available));
}

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
    return http_get($url);
}

function get_binance_price($symbol)
{
    $data = binance_get('/api/v3/ticker/price', array('symbol' => normalize_symbol($symbol)));
    return $data['price'];
}

function get_binance_order_book($symbol, $limit = 20)
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

// ==================== 核心：价格区间 ====================

function build_price_ranges($currentPrice, $tickSize, $levels, $direction, $nearLevels)
{
    $totalNearTicks = NEAR_TICKS_PER_DOM * $nearLevels;
    $nearOffset = bcmul((string)$totalNearTicks, $tickSize, 20);
    $nearPctWidth = bcdiv(bcmul($nearOffset, '100', 10), $currentPrice, 10);

    $totalPctWidth = '50';
    $remainPctWidth = bcsub($totalPctWidth, $nearPctWidth, 10);
    if (bccomp($remainPctWidth, '0', 10) <= 0) {
        $remainPctWidth = '0.001';
    }

    $remainLevels = $levels - $nearLevels;
    $nearPerDom   = bcdiv($nearPctWidth, (string)$nearLevels, 10);
    $remainPerDom = $remainLevels > 0 ? bcdiv($remainPctWidth, (string)$remainLevels, 10) : '0';

    $ranges    = array();
    $cursorPct = '100';

    for ($dom = 1; $dom <= $levels; $dom++) {
        $isNear = ($dom <= $nearLevels);
        $widthPct = $isNear ? $nearPerDom : $remainPerDom;
        $isLast = ($dom === $levels);

        if ($direction === -1) {
            $lowPct  = $cursorPct;
            $highPct = $isLast ? '150' : bcadd($cursorPct, $widthPct, 10);
            $ranges[] = array($lowPct, $highPct);
            $cursorPct = $highPct;
        } else {
            $highPct = $cursorPct;
            $lowPct  = $isLast ? '50' : bcsub($cursorPct, $widthPct, 10);
            $ranges[] = array($lowPct, $highPct);
            $cursorPct = $lowPct;
        }
    }

    return $ranges;
}

// ==================== 配置生成 ====================

function generate_configs($symbol, $levels, $totalUsdt, $pid, $currentPrice, $localInfo, $orderBook)
{
    $tickSize = $localInfo['tickSize'];
    $stepSize = $localInfo['stepSize'];

    $nearLevels = ($levels > 6) ? 2 : 1;
    $remainLevels = $levels - $nearLevels;

    $totalTrust = 1000;

    $nearDepthQty  = calc_depth_avg_qty($orderBook, DEPTH_NEAR);
    $otherDepthQty = calc_depth_avg_qty($orderBook, DEPTH_OTHER);
    $nearNumberFloat  = make_number_float($nearDepthQty, $stepSize);
    $otherNumberFloat = make_number_float($otherDepthQty, $stepSize);

    // 近盘 trust_num = tick数 × 填充率
    $nearTrustPerDom = max(1, (int)round(NEAR_TICKS_PER_DOM * NEAR_FILL_RATE));
    $nearTrustTotal = $nearTrustPerDom * $nearLevels;
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
                '_zone'                 => $isNear ? '近盘' : '均分',
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

    // UPDATE 语句：按 pid + direction + dom 更新每档
    $sql .= "\n-- UPDATE 语句（按 pid + direction + dom 逐档更新）\n";
    foreach ($configs as $c) {
        $sets = array();
        foreach ($fields as $f) {
            if ($f === 'box_id' || $f === 'pid' || $f === 'direction' || $f === 'dom') {
                continue;
            }
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

    file_put_contents($outputPath, $sql);
    echo "[输出] SQL: {$outputPath}\n";
}

// ==================== 控制台输出 ====================

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

function pct_to_actual($priceFloatPct, $refPrice, $pricePrecision)
{
    $parts = explode('-', $priceFloatPct);
    $low  = bcadd(bcdiv(bcmul($refPrice, $parts[0], 10), '100', $pricePrecision), '0', $pricePrecision);
    $high = bcadd(bcdiv(bcmul($refPrice, $parts[1], 10), '100', $pricePrecision), '0', $pricePrecision);
    return $low . ' ~ ' . $high;
}

function print_output($configs, $levels, $currentPrice, $localInfo, $symbol, $pid, $totalUsdt, $depthRatio)
{
    $tickSize       = $localInfo['tickSize'];
    $pricePrecision = $localInfo['price_precision'];
    $nearLevels     = ($levels > 6) ? 2 : 1;
    $totalNearTicks = NEAR_TICKS_PER_DOM * $nearLevels;
    $nearOffset     = bcmul((string)$totalNearTicks, $tickSize, 10);
    $nearPct        = bcdiv(bcmul($nearOffset, '100', 10), $currentPrice, 4);
    $symbolDisplay  = strtoupper(str_replace('_', '/', $symbol));

    $sep = str_repeat('-', 75);
    echo "\n{$sep}\n";
    echo "  交易对     : {$symbolDisplay}  ({$localInfo['display']})  当前价: {$currentPrice}\n";
    echo "  本所精度   : 价格 {$pricePrecision} 位 (tickSize={$tickSize})   数量 {$localInfo['number_precision']} 位\n";
    echo "  最小挂单量 : {$localInfo['min_trade']}   最大: {$localInfo['max_trade']}\n";
    echo sprintf("  pid: %d   levels: %d   total: %s USDT\n", $pid, $levels, number_format($totalUsdt, 0));
    echo "  近盘: 每档 " . NEAR_TICKS_PER_DOM . " 价格位 × {$nearLevels} 档 = {$totalNearTicks} 价格位 ({$nearPct}%)\n";
    echo "  填充率: " . (NEAR_FILL_RATE * 100) . "% → trust_num = " . (int)round(NEAR_TICKS_PER_DOM * NEAR_FILL_RATE) . "\n";
    echo "{$sep}\n\n";

    // 分组
    $sellMap = array();
    $buyMap  = array();
    foreach ($configs as $c) {
        if ($c['direction'] === -1) {
            $sellMap[$c['dom']] = $c;
        } else {
            $buyMap[$c['dom']] = $c;
        }
    }

    echo sprintf(" %-3s %-6s %6s %8s %7s  %-28s  %-16s\n",
        'dom', '区域', '笔数', '价格位数', '笔/位', '价格区间(%)', '数量区间');
    echo str_repeat('-', 95) . "\n";

    for ($dom = 1; $dom <= $levels; $dom++) {
        $sc = isset($sellMap[$dom]) ? $sellMap[$dom] : array();
        $zone      = isset($sc['_zone']) ? $sc['_zone'] : '';
        $trustNum  = isset($sc['trust_num']) ? $sc['trust_num'] : 0;
        $sellPf    = isset($sc['price_float']) ? $sc['price_float'] : '-';
        $numFloat  = isset($sc['number_float']) ? $sc['number_float'] : '-';
        $ticks     = $sellPf !== '-' ? ticks_count($sellPf, $currentPrice, $tickSize) : 0;
        $fillRatio = $ticks > 0 ? sprintf('%.2f', $trustNum / $ticks) : '-';

        echo sprintf(" %-3d %-6s %6d %8d %7s  %-28s  %-16s\n",
            $dom, $zone, $trustNum, $ticks, $fillRatio, $sellPf, $numFloat);
    }
    echo "\n";

    // 实际价格
    echo " 卖方实际价格:\n";
    for ($dom = 1; $dom <= $levels; $dom++) {
        $sc = isset($sellMap[$dom]) ? $sellMap[$dom] : array();
        $actual = isset($sc['price_float']) ? pct_to_actual($sc['price_float'], $currentPrice, $pricePrecision) : '-';
        echo sprintf("   dom%-2d  %s\n", $dom, $actual);
    }
    echo "\n 买方实际价格:\n";
    for ($dom = 1; $dom <= $levels; $dom++) {
        $bc = isset($buyMap[$dom]) ? $buyMap[$dom] : array();
        $actual = isset($bc['price_float']) ? pct_to_actual($bc['price_float'], $currentPrice, $pricePrecision) : '-';
        echo sprintf("   dom%-2d  %s\n", $dom, $actual);
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
        echo "用法: php generate_box_config.php --symbol trx_usdt --pid 3 --levels 9 \\\n";
        echo "      --total_usdt 2000000 --depth_ratio 0.3\n\n";
        echo "精度自动从本所 exchangeInfo 获取，无需手动指定。\n";
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
    $symbol = $args['symbol'];

    // 1. 本所精度
    echo "[本所] 正在获取 {$symbol} 精度信息...\n";
    try {
        $localInfo = get_local_exchange_info($symbol);
    } catch (Exception $e) {
        fwrite(STDERR, "[错误] " . $e->getMessage() . "\n");
        exit(1);
    }
    echo "[本所] price_precision={$localInfo['price_precision']}  tickSize={$localInfo['tickSize']}  min_trade={$localInfo['min_trade']}\n";

    // 2. 币安价格+深度
    echo "[币安] 正在获取参考价格和深度...\n";
    try {
        $currentPrice = get_binance_price($symbol);
        $orderBook    = get_binance_order_book($symbol, 20);
    } catch (Exception $e) {
        fwrite(STDERR, "[错误] 币安: " . $e->getMessage() . "\n");
        exit(1);
    }
    echo "[币安] 参考价格: {$currentPrice}\n";

    // 3. 生成
    $configs = generate_configs(
        $symbol, $args['levels'], $args['total_usdt'], $args['pid'],
        $currentPrice, $localInfo, $orderBook
    );

    // 4. 输出
    print_output($configs, $args['levels'], $currentPrice, $localInfo,
        $symbol, $args['pid'], $args['total_usdt'], $args['depth_ratio']);

    $sqlPath = $args['output_dir'] . '/' . $symbol . '_pid' . $args['pid'] . '.sql';
    generate_sql($configs, $sqlPath);
}

main();
