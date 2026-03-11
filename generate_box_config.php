<?php
/**
 * 现货铺单配置生成器 (PHP 7.3+ 版)
 *
 * 用法:
 *   php generate_box_config.php --symbol eth_usdt --pid 3 --levels 9 \
 *       --total_usdt 2000000 --depth_ratio 0.3
 *
 * 参数:
 *   --symbol       交易对 (btc_usdt / eth_usdt)
 *   --pid          项目 ID
 *   --levels       每侧档位数 (默认 6)
 *   --total_usdt   总量 USDT (默认 1000000)
 *   --depth_ratio  深度比 (默认 0.2)
 *   --output_dir   输出目录 (默认 ./output)
 *   --near_ticks   近盘 tick 数 (默认 100)
 *   --mid_ticks    中盘 tick 数 (默认 2000)
 *   --far_pct      远盘最远百分比 (默认 5.0，即上下 5%)
 */

bcscale(20);

// ==================== 常量 ====================

// 近盘：前 N 个 tick（紧贴当前价），铺满 80%
define('DEFAULT_NEAR_TICKS', 100);

// 中盘：近盘之后 N 个 tick
define('DEFAULT_MID_TICKS', 2000);

// 远盘：中盘之后到 far_pct% 的范围
define('DEFAULT_FAR_PCT', 5.0);

// 盘口深度取值档位
define('DEPTH_LEVELS', array(
    'near' => 2,
    'mid'  => 8,
    'far'  => 20,
));

// trust_num 分配比例（近盘少量高频，远盘大量低频）
define('ZONE_TRUST_RATIOS', array(
    'near' => 0.15,
    'mid'  => 0.45,
    'far'  => 0.40,
));

define('BINANCE_BASE_URL', 'https://api.binance.com');
define('REQUEST_TIMEOUT', 10);

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
    $filterList = isset($symbols[0]['filters']) ? $symbols[0]['filters'] : array();
    foreach ($filterList as $f) {
        $filters[$f['filterType']] = $f;
    }

    $tickSize = null;
    if (isset($filters['PRICE_FILTER']['tickSize'])) {
        $tickSize = $filters['PRICE_FILTER']['tickSize'];
    } elseif (isset($filters['LOT_SIZE']['stepSize'])) {
        $tickSize = $filters['LOT_SIZE']['stepSize'];
    }

    $stepSize = isset($filters['LOT_SIZE']['stepSize']) ? $filters['LOT_SIZE']['stepSize'] : null;
    $minQty   = isset($filters['LOT_SIZE']['minQty']) ? $filters['LOT_SIZE']['minQty'] : null;

    if (!$tickSize || !$stepSize) {
        throw new RuntimeException("未找到 tickSize/stepSize 信息: {$symbol}");
    }

    return array(
        'tickSize' => $tickSize,
        'stepSize' => $stepSize,
        'minQty'   => $minQty,
    );
}

function get_order_book($symbol, $limit = 20)
{
    return binance_get('/api/v3/depth', array(
        'symbol' => normalize_symbol($symbol),
        'limit'  => $limit,
    ));
}

// ==================== 工具函数 ====================

function decimal_places($tickStr)
{
    $tickStr = rtrim(rtrim($tickStr, '0'), '.');
    $pos = strpos($tickStr, '.');
    return $pos === false ? 0 : strlen($tickStr) - $pos - 1;
}

function format_price($value, $tickSize)
{
    $places = decimal_places($tickSize);
    return bcadd($value, '0', $places);
}

function format_qty($value, $stepSize)
{
    $places = decimal_places($stepSize);
    $factor = bcpow('10', (string)$places);
    return bcdiv(bcmul($value, $factor, 0), $factor, $places);
}

// ==================== 区间计算 ====================

/**
 * 根据档位数分配近/中/远盘
 *
 * 原则：
 *   - 近盘占 1-2 档（levels<=6 取 1 档，>6 取 2 档）
 *   - 远盘占 1-2 档
 *   - 中盘占剩余
 */
function compute_zones($levels)
{
    if ($levels <= 3) {
        $near = array(1);
        $far  = array($levels);
        $mid  = array();
        for ($i = 2; $i < $levels; $i++) {
            $mid[] = $i;
        }
    } elseif ($levels <= 6) {
        $near = array(1);
        $mid  = array();
        $far  = array();
        for ($i = 2; $i <= $levels - 2; $i++) {
            $mid[] = $i;
        }
        for ($i = max(2, $levels - 1); $i <= $levels; $i++) {
            $far[] = $i;
        }
    } else {
        $near = array(1, 2);
        $far  = array($levels - 1, $levels);
        $mid  = array();
        for ($i = 3; $i <= $levels - 2; $i++) {
            $mid[] = $i;
        }
    }

    return array(
        'near' => $near,
        'mid'  => $mid,
        'far'  => $far,
    );
}

function zone_of($dom, $zones)
{
    if (in_array($dom, $zones['near'])) return 'near';
    if (in_array($dom, $zones['mid'])) return 'mid';
    return 'far';
}

// ==================== 盘口深度计算 ====================

function cumulative_qty($side, $depth)
{
    $total = '0';
    $count = min($depth, count($side));
    for ($i = 0; $i < $count; $i++) {
        $total = bcadd($total, $side[$i][1]);
    }
    return $total;
}

function calc_number_float($orderBook, $zone, $stepSize)
{
    $depthLevels = DEPTH_LEVELS;
    $depth  = $depthLevels[$zone];
    $bids   = isset($orderBook['bids']) ? $orderBook['bids'] : array();
    $asks   = isset($orderBook['asks']) ? $orderBook['asks'] : array();
    $bidQty = cumulative_qty($bids, $depth);
    $askQty = cumulative_qty($asks, $depth);
    $avgQty = bcdiv(bcadd($bidQty, $askQty), '2', 20);

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

// ==================== 价格区间计算（基于 tick 数） ====================

/**
 * 基于实际 tick 数计算各档位价格百分比区间
 *
 * 核心逻辑：
 *   近盘 = 当前价 ± nearTicks × tickSize → 转为百分比
 *   中盘 = 近盘边界 ± midTicks × tickSize → 转为百分比
 *   远盘 = 中盘边界到 farPct% 范围
 *
 * 这样不同价格/精度的币种，近盘永远是紧贴当前价的 N 个 tick
 */
function build_price_ranges($currentPrice, $tickSize, $levels, $direction, $nearTicks, $midTicks, $farPct)
{
    $price = $currentPrice;
    $zones = compute_zones($levels);
    $nearCount = count($zones['near']);
    $midCount  = count($zones['mid']);
    $farCount  = count($zones['far']);

    // 各区间的实际价格偏移量
    $nearOffset = bcmul((string)$nearTicks, $tickSize, 20);
    $midOffset  = bcmul((string)$midTicks, $tickSize, 20);

    // 转为百分比偏移（相对当前价）
    // nearPctWidth = nearOffset / price * 100
    $nearPctWidth = bcdiv(bcmul($nearOffset, '100', 10), $price, 10);
    $midPctWidth  = bcdiv(bcmul($midOffset, '100', 10), $price, 10);
    $farPctWidth  = (string)$farPct;

    // 总范围 = near + mid + far
    $totalPctWidth = bcadd(bcadd($nearPctWidth, $midPctWidth, 10), $farPctWidth, 10);

    // 每档的百分比宽度
    $nearPerDom = $nearCount > 0 ? bcdiv($nearPctWidth, (string)$nearCount, 10) : '0';
    $midPerDom  = $midCount > 0 ? bcdiv($midPctWidth, (string)$midCount, 10) : '0';
    $farPerDom  = $farCount > 0 ? bcdiv($farPctWidth, (string)$farCount, 10) : '0';

    $ranges    = array();
    $cursorPct = '100';

    for ($dom = 1; $dom <= $levels; $dom++) {
        $zone = zone_of($dom, $zones);
        switch ($zone) {
            case 'near': $widthPct = $nearPerDom; break;
            case 'mid':  $widthPct = $midPerDom; break;
            default:     $widthPct = $farPerDom; break;
        }

        $isLast = ($dom === $levels);

        if ($direction === -1) {
            // 卖方：100% 向上
            $lowPct  = $cursorPct;
            if ($isLast) {
                $highPct = bcadd('100', $totalPctWidth, 10);
            } else {
                $highPct = bcadd($cursorPct, $widthPct, 10);
            }
            $ranges[] = array($lowPct, $highPct);
            $cursorPct = $highPct;
        } else {
            // 买方：100% 向下
            $highPct = $cursorPct;
            if ($isLast) {
                $lowPct = bcsub('100', $totalPctWidth, 10);
            } else {
                $lowPct = bcsub($cursorPct, $widthPct, 10);
            }
            $ranges[] = array($lowPct, $highPct);
            $cursorPct = $lowPct;
        }
    }

    return $ranges;
}

// ==================== 配置生成 ====================

function generate_configs($symbol, $levels, $totalUsdt, $pid, $currentPrice, $exchangeInfo, $orderBook, $nearTicks, $midTicks, $farPct)
{
    $tickSize = $exchangeInfo['tickSize'];
    $stepSize = $exchangeInfo['stepSize'];
    $zones    = compute_zones($levels);

    // trust_num 按区间比例分配
    $totalTrust = 1000;
    $trustRatios = ZONE_TRUST_RATIOS;

    $configs = array();
    $directions = array(-1, 1);

    foreach ($directions as $direction) {
        $priceRanges = build_price_ranges($currentPrice, $tickSize, $levels, $direction, $nearTicks, $midTicks, $farPct);

        $zoneNumberFloat = array();
        $zoneNames = array('near', 'mid', 'far');
        foreach ($zoneNames as $zone) {
            $zoneNumberFloat[$zone] = calc_number_float($orderBook, $zone, $stepSize);
        }

        for ($dom = 1; $dom <= $levels; $dom++) {
            $zone = zone_of($dom, $zones);
            $zoneCount = count($zones[$zone]);

            // trust_num = 总量 × 区间比例 / 该区间档位数
            $ratio = $trustRatios[$zone];
            $trustNum = max(1, (int)round($totalTrust * $ratio / max(1, $zoneCount)));

            $lowPct  = $priceRanges[$dom - 1][0];
            $highPct = $priceRanges[$dom - 1][1];
            $priceFloat = bcadd($lowPct, '0', 3) . '-' . bcadd($highPct, '0', 3);

            $numberFloat       = $zoneNumberFloat[$zone];
            $changeNumberFloat = $numberFloat;
            $changeTrustNum    = in_array($dom, $zones['near']) ? 0 : 1;
            $changeSurvival    = in_array($dom, $zones['near']) ? '3-10' : '10-30';

            $configs[] = array(
                'box_id'                => null,
                'pid'                   => $pid,
                'direction'             => $direction,
                'dom'                   => $dom,
                'trust_num'             => $trustNum,
                'price_float'           => $priceFloat,
                'number_float'          => $numberFloat,
                'change_trust_num'      => $changeTrustNum,
                'change_number_float'   => $changeNumberFloat,
                'change_survival_time'  => $changeSurvival,
                'status'                => 1,
                '_symbol'               => $symbol,
                '_zone'                 => $zone,
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

function pct_to_actual($priceFloatPct, $referencePrice)
{
    $parts = explode('-', $priceFloatPct);
    $lowS  = $parts[0];
    $highS = $parts[1];
    $lowPrice  = bcdiv(bcmul($referencePrice, $lowS, 10), '100', 6);
    $highPrice = bcdiv(bcmul($referencePrice, $highS, 10), '100', 6);
    return $lowPrice . '-' . $highPrice;
}

function ticks_in_range($priceFloatPct, $referencePrice, $tickSize)
{
    $parts = explode('-', $priceFloatPct);
    $lowPrice  = bcdiv(bcmul($referencePrice, $parts[0], 10), '100', 10);
    $highPrice = bcdiv(bcmul($referencePrice, $parts[1], 10), '100', 10);
    $diff = bcsub($highPrice, $lowPrice, 10);
    if (bccomp($diff, '0', 10) < 0) {
        $diff = bcmul($diff, '-1', 10);
    }
    return (int)bcdiv($diff, $tickSize, 0);
}

function print_header($symbol, $currentPrice, $pid, $levels, $totalUsdt, $depthRatio, $recordCount, $tickSize, $nearTicks, $midTicks, $farPct)
{
    $singleSide    = $totalUsdt * $depthRatio / 2;
    $symbolDisplay = strtoupper(str_replace('_', '/', $symbol));
    $sellCount     = intdiv($recordCount, 2);
    $buyCount      = $recordCount - $sellCount;
    $tickPlaces    = decimal_places($tickSize);

    $sep = str_repeat('-', 70);
    echo "\n{$sep}\n";
    echo "  交易对     : {$symbolDisplay}  (参考价: {$currentPrice})\n";
    echo "  tickSize   : {$tickSize} ({$tickPlaces} 位精度)\n";
    echo sprintf("  pid        : %d   档位数: %d   总量: %s USDT\n", $pid, $levels, number_format($totalUsdt, 0));
    echo sprintf("  深度比     : %.1f   单边有效量: %s USDT\n", $depthRatio, number_format($singleSide, 0));
    echo sprintf("  近盘 ticks : %d   中盘 ticks: %d   远盘: %.1f%%\n", $nearTicks, $midTicks, $farPct);
    echo "  生成记录   : {$recordCount} 条 ({$sellCount} 卖单 + {$buyCount} 买单)\n";
    echo "{$sep}\n\n";
}

function print_table($configs, $levels, $referencePrice, $tickSize)
{
    $sellMap = array();
    $buyMap  = array();
    foreach ($configs as $c) {
        if ($c['direction'] === -1) {
            $sellMap[$c['dom']] = $c;
        } else {
            $buyMap[$c['dom']] = $c;
        }
    }

    $zoneCn = array('near' => '近盘', 'mid' => '中盘', 'far' => '远盘');

    echo sprintf("%-4s %-6s %6s %6s  %-24s  %-24s\n", '档位', '区域', '委托数', 'ticks', '卖 price_float(%)', '买 price_float(%)');
    echo str_repeat('-', 85) . "\n";

    for ($dom = 1; $dom <= $levels; $dom++) {
        $sc = isset($sellMap[$dom]) ? $sellMap[$dom] : array();
        $bc = isset($buyMap[$dom]) ? $buyMap[$dom] : array();
        $zoneKey   = isset($sc['_zone']) ? $sc['_zone'] : '';
        $zoneLabel = isset($zoneCn[$zoneKey]) ? $zoneCn[$zoneKey] : '';
        $trustNum  = isset($sc['trust_num']) ? $sc['trust_num'] : '-';
        $sellPf    = isset($sc['price_float']) ? $sc['price_float'] : '-';
        $buyPf     = isset($bc['price_float']) ? $bc['price_float'] : '-';
        $ticks     = $sellPf !== '-' ? ticks_in_range($sellPf, $referencePrice, $tickSize) : '-';
        echo sprintf(" %-3d %-6s %6s %6s  %-24s  %-24s\n", $dom, $zoneLabel, $trustNum, $ticks, $sellPf, $buyPf);
    }
    echo "\n";
}

function print_summary($configs, $referencePrice, $tickSize)
{
    $header = sprintf(
        "%-4s %-4s %-6s %6s %6s %-22s %-22s %-16s %6s %-8s",
        '方向', '档位', '区间', '笔数', 'ticks', '价格区间(%)', '实际价格', '数量区间', '变幻', '存活'
    );
    $sep = str_repeat('-', strlen($header) + 10);

    echo "\n" . str_repeat('=', strlen($header) + 10) . "\n";
    echo " 铺单配置摘要\n";
    echo str_repeat('=', strlen($header) + 10) . "\n";
    echo $header . "\n";
    echo $sep . "\n";

    $zoneCn = array('near' => '近盘', 'mid' => '中盘', 'far' => '远盘');

    foreach ($configs as $c) {
        $actual    = pct_to_actual($c['price_float'], $referencePrice);
        $zoneKey   = isset($c['_zone']) ? $c['_zone'] : '';
        $zoneLabel = isset($zoneCn[$zoneKey]) ? $zoneCn[$zoneKey] : '';
        $ticks     = ticks_in_range($c['price_float'], $referencePrice, $tickSize);
        echo sprintf(
            " %-4s %-4d %-6s %6d %6d %-22s %-22s %-16s %6d %-8s\n",
            $c['_direction_label'],
            $c['dom'],
            $zoneLabel,
            $c['trust_num'],
            $ticks,
            $c['price_float'],
            $actual,
            $c['number_float'],
            $c['change_trust_num'],
            $c['change_survival_time']
        );
    }

    echo $sep . "\n";
    echo sprintf("共 %d 条配置\n\n", count($configs));
}

// ==================== CLI 入口 ====================

function parse_args()
{
    $opts = getopt('', array(
        'symbol:', 'pid:', 'levels:', 'total_usdt:', 'depth_ratio:', 'output_dir:',
        'near_ticks:', 'mid_ticks:', 'far_pct:',
    ));

    if (empty($opts['symbol']) || !isset($opts['pid'])) {
        echo "现货铺单配置生成器 (PHP 7.3+ 版)\n\n";
        echo "用法:\n";
        echo "  php generate_box_config.php --symbol trx_usdt --pid 3 --levels 9 \\\n";
        echo "      --total_usdt 2000000 --depth_ratio 0.3\n\n";
        echo "参数:\n";
        echo "  --symbol       交易对 (必填，如 trx_usdt / eth_usdt)\n";
        echo "  --pid          项目 ID (必填)\n";
        echo "  --levels       每侧档位数 (默认 6)\n";
        echo "  --total_usdt   总量 USDT (默认 1000000)\n";
        echo "  --depth_ratio  深度比 (默认 0.2)\n";
        echo "  --output_dir   输出目录 (默认 ./output)\n";
        echo "  --near_ticks   近盘 tick 数 (默认 100)\n";
        echo "  --mid_ticks    中盘 tick 数 (默认 2000)\n";
        echo "  --far_pct      远盘最远百分比 (默认 5.0)\n";
        exit(1);
    }

    return array(
        'symbol'      => strtolower($opts['symbol']),
        'pid'         => (int)$opts['pid'],
        'levels'      => isset($opts['levels']) ? (int)$opts['levels'] : 6,
        'total_usdt'  => isset($opts['total_usdt']) ? (float)$opts['total_usdt'] : 1000000.0,
        'depth_ratio' => isset($opts['depth_ratio']) ? (float)$opts['depth_ratio'] : 0.2,
        'output_dir'  => isset($opts['output_dir']) ? $opts['output_dir'] : 'output',
        'near_ticks'  => isset($opts['near_ticks']) ? (int)$opts['near_ticks'] : DEFAULT_NEAR_TICKS,
        'mid_ticks'   => isset($opts['mid_ticks']) ? (int)$opts['mid_ticks'] : DEFAULT_MID_TICKS,
        'far_pct'     => isset($opts['far_pct']) ? (float)$opts['far_pct'] : DEFAULT_FAR_PCT,
    );
}

function main()
{
    $args = parse_args();

    $symbol     = $args['symbol'];
    $pid        = $args['pid'];
    $levels     = $args['levels'];
    $totalUsdt  = $args['total_usdt'];
    $depthRatio = $args['depth_ratio'];
    $outputDir  = $args['output_dir'];
    $nearTicks  = $args['near_ticks'];
    $midTicks   = $args['mid_ticks'];
    $farPct     = $args['far_pct'];

    // 1. 拉取币安数据
    echo "[API] 正在获取 " . strtoupper($symbol) . " 行情数据...\n";

    try {
        $currentPrice = get_price($symbol);
        $exchangeInfo = get_exchange_info($symbol);
        $orderBook    = get_order_book($symbol, 20);
    } catch (Exception $e) {
        fwrite(STDERR, "[错误] 币安 API 请求失败: " . $e->getMessage() . "\n");
        exit(1);
    }

    $tickSize = $exchangeInfo['tickSize'];
    echo "[API] 参考价格: {$currentPrice}  tickSize: {$tickSize}\n";

    // 显示近盘实际覆盖的价格范围
    $nearOffset = bcmul((string)$nearTicks, $tickSize, 10);
    $nearPct    = bcdiv(bcmul($nearOffset, '100', 10), $currentPrice, 4);
    echo "[计算] 近盘 {$nearTicks} ticks = {$nearOffset} 价格偏移 = {$nearPct}%\n";

    // 2. 生成配置
    $configs = generate_configs(
        $symbol,
        $levels,
        $totalUsdt,
        $pid,
        $currentPrice,
        $exchangeInfo,
        $orderBook,
        $nearTicks,
        $midTicks,
        $farPct
    );

    // 3. 输出摘要
    print_header($symbol, $currentPrice, $pid, $levels, $totalUsdt, $depthRatio, count($configs), $tickSize, $nearTicks, $midTicks, $farPct);
    print_table($configs, $levels, $currentPrice, $tickSize);
    print_summary($configs, $currentPrice, $tickSize);

    // 4. 生成 SQL
    $safeSymbol = str_replace('/', '_', $symbol);
    $sqlPath = $outputDir . '/' . $safeSymbol . '_pid' . $pid . '.sql';
    generate_sql($configs, $sqlPath);
}

main();
