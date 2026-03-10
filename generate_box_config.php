<?php
/**
 * 现货铺单配置生成器 (PHP 版)
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
 */

declare(strict_types=1);
bcscale(20);

// ==================== 常量 ====================

const NEAR_TICK_BOUNDARY = 150;
const MID_TICK_BOUNDARY  = 100_000;

const DEPTH_LEVELS = [
    'near' => 2,
    'mid'  => 8,
    'far'  => 20,
];

const ZONE_TRUST_MULTIPLIERS = [
    'near' => '0.4',
    'mid'  => '0.8',
    'far'  => '1.2',
];

const BINANCE_BASE_URL = 'https://api.binance.com';
const REQUEST_TIMEOUT  = 10;

// ==================== 币安 API ====================

function normalize_symbol(string $symbol): string
{
    return strtoupper(str_replace('_', '', $symbol));
}

function binance_get(string $path, array $params = []): array
{
    $url = BINANCE_BASE_URL . $path;
    if ($params) {
        $url .= '?' . http_build_query($params);
    }

    $ch = curl_init($url);
    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT        => REQUEST_TIMEOUT,
        CURLOPT_SSL_VERIFYPEER => true,
        CURLOPT_HTTPHEADER     => ['Accept: application/json'],
    ]);

    $response = curl_exec($ch);
    $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $error    = curl_error($ch);
    curl_close($ch);

    if ($response === false) {
        throw new RuntimeException("币安 API 请求失败: {$error}");
    }
    if ($httpCode !== 200) {
        throw new RuntimeException("币安 API 请求失败: HTTP {$httpCode} - {$response}");
    }

    return json_decode($response, true);
}

function get_price(string $symbol): string
{
    $data = binance_get('/api/v3/ticker/price', ['symbol' => normalize_symbol($symbol)]);
    return $data['price'];
}

function get_exchange_info(string $symbol): array
{
    $data    = binance_get('/api/v3/exchangeInfo', ['symbol' => normalize_symbol($symbol)]);
    $symbols = $data['symbols'] ?? [];

    if (empty($symbols)) {
        throw new RuntimeException("未找到交易对信息: {$symbol}");
    }

    $filters = [];
    foreach ($symbols[0]['filters'] ?? [] as $f) {
        $filters[$f['filterType']] = $f;
    }

    $tickSize = $filters['PRICE_FILTER']['tickSize']
        ?? $filters['LOT_SIZE']['stepSize']
        ?? null;

    $stepSize = $filters['LOT_SIZE']['stepSize'] ?? null;

    if (!$tickSize || !$stepSize) {
        throw new RuntimeException("未找到 tickSize/stepSize 信息: {$symbol}");
    }

    return ['tickSize' => $tickSize, 'stepSize' => $stepSize];
}

function get_order_book(string $symbol, int $limit = 20): array
{
    return binance_get('/api/v3/depth', [
        'symbol' => normalize_symbol($symbol),
        'limit'  => $limit,
    ]);
}

// ==================== 工具函数 ====================

function decimal_places(string $tickStr): int
{
    $tickStr = rtrim(rtrim($tickStr, '0'), '.');
    $pos = strpos($tickStr, '.');
    return $pos === false ? 0 : strlen($tickStr) - $pos - 1;
}

function format_price(string $value, string $tickSize): string
{
    $places = decimal_places($tickSize);
    return bcadd($value, '0', $places); // 截断到精度
}

function format_qty(string $value, string $stepSize): string
{
    $places = decimal_places($stepSize);
    // 向下截断
    $factor = bcpow('10', (string)$places);
    $truncated = bcdiv(bcmul($value, $factor, 0), $factor, $places);
    return $truncated;
}

// ==================== 区间计算 ====================

function compute_zones(int $levels): array
{
    if ($levels <= 3) {
        $near = [1];
        $far  = [$levels];
        $mid  = [];
        for ($i = 2; $i < $levels; $i++) $mid[] = $i;
    } elseif ($levels <= 6) {
        $near = [1];
        $mid  = [2, 3];
        $far  = [];
        for ($i = 4; $i <= $levels; $i++) $far[] = $i;
    } else {
        $near = [1, 2];
        $far  = [$levels - 1, $levels];
        $mid  = [];
        for ($i = 3; $i <= $levels - 2; $i++) $mid[] = $i;
    }

    return [
        'near' => $near,
        'mid'  => $mid,
        'far'  => $far,
    ];
}

function zone_of(int $dom, array $zones): string
{
    if (in_array($dom, $zones['near'])) return 'near';
    if (in_array($dom, $zones['mid'])) return 'mid';
    return 'far';
}

// ==================== 盘口深度计算 ====================

function cumulative_qty(array $side, int $depth): string
{
    $total = '0';
    for ($i = 0; $i < min($depth, count($side)); $i++) {
        $total = bcadd($total, $side[$i][1]);
    }
    return $total;
}

function calc_number_float(array $orderBook, string $zone, string $stepSize): string
{
    $depth  = DEPTH_LEVELS[$zone];
    $bidQty = cumulative_qty($orderBook['bids'] ?? [], $depth);
    $askQty = cumulative_qty($orderBook['asks'] ?? [], $depth);
    $avgQty = bcdiv(bcadd($bidQty, $askQty), '2');

    $base = bcmul($avgQty, '0.2');
    if (bccomp($base, $stepSize) < 0) {
        $base = $stepSize;
    }

    $qtyMin = format_qty(bcmul($base, '0.5'), $stepSize);
    $qtyMax = format_qty($base, $stepSize);

    if ($qtyMin === $qtyMax) {
        $qtyMin = format_qty($stepSize, $stepSize);
    }

    return "{$qtyMin}-{$qtyMax}";
}

// ==================== 价格区间计算 ====================

function build_price_ranges(string $currentPrice, string $tickSize, int $levels, int $direction): array
{
    $totalTicks = max(1, intval(bcdiv(bcmul($currentPrice, '0.5'), $tickSize, 0)));

    $nearEnd = min(NEAR_TICK_BOUNDARY, $totalTicks);
    $midEnd  = min(MID_TICK_BOUNDARY, $totalTicks);

    $nearTicksRaw = $nearEnd;
    $midTicksRaw  = $midEnd - $nearEnd;
    $farTicksRaw  = $totalTicks - $midEnd;

    $zones     = compute_zones($levels);
    $nearCount = count($zones['near']);
    $midCount  = count($zones['mid']);
    $farCount  = count($zones['far']);

    $effectiveNear = max($nearCount, $nearTicksRaw);
    $effectiveMid  = max($midCount, $midTicksRaw);
    $effectiveFar  = max($farCount, $farTicksRaw);
    $totalEffective = (string)($effectiveNear + $effectiveMid + $effectiveFar);

    $totalEffective = max(1, (int)$totalEffective);
    $teStr = (string)$totalEffective;
    $nearPctTotal = bcdiv(bcmul((string)$effectiveNear, '50'), $teStr, 10);
    $midPctTotal  = bcdiv(bcmul((string)$effectiveMid, '50'), $teStr, 10);
    $farPctTotal  = bcdiv(bcmul((string)$effectiveFar, '50'), $teStr, 10);

    $nearPerDom = $nearCount > 0 ? bcdiv($nearPctTotal, (string)$nearCount, 10) : '0';
    $midPerDom  = $midCount > 0 ? bcdiv($midPctTotal, (string)$midCount, 10) : '0';
    $farPerDom  = $farCount > 0 ? bcdiv($farPctTotal, (string)$farCount, 10) : '0';

    $ranges    = [];
    $cursorPct = '100';

    for ($dom = 1; $dom <= $levels; $dom++) {
        $zone = zone_of($dom, $zones);
        $widthPct = match ($zone) {
            'near' => $nearPerDom,
            'mid'  => $midPerDom,
            'far'  => $farPerDom,
        };

        $isLast = ($dom === $levels);

        if ($direction === -1) {
            // 卖方：100% 向上
            $lowPct  = $cursorPct;
            $highPct = $isLast ? '150' : bcadd($cursorPct, $widthPct);
            $ranges[] = [$lowPct, $highPct];
            $cursorPct = $highPct;
        } else {
            // 买方：100% 向下
            $highPct = $cursorPct;
            $lowPct  = $isLast ? '50' : bcsub($cursorPct, $widthPct);
            $ranges[] = [$lowPct, $highPct];
            $cursorPct = $lowPct;
        }
    }

    return $ranges;
}

// ==================== 配置生成 ====================

function generate_configs(
    string $symbol,
    int    $levels,
    float  $totalUsdt,
    int    $pid,
    string $currentPrice,
    array  $exchangeInfo,
    array  $orderBook,
): array {
    $tickSize = $exchangeInfo['tickSize'];
    $stepSize = $exchangeInfo['stepSize'];
    $zones    = compute_zones($levels);

    $totalTrust = 1000;
    $baseTrust  = $totalTrust / $levels;

    $configs = [];

    foreach ([-1, 1] as $direction) {
        $priceRanges = build_price_ranges($currentPrice, $tickSize, $levels, $direction);

        $zoneNumberFloat = [];
        foreach (['near', 'mid', 'far'] as $zone) {
            $zoneNumberFloat[$zone] = calc_number_float($orderBook, $zone, $stepSize);
        }

        for ($dom = 1; $dom <= $levels; $dom++) {
            $zone = zone_of($dom, $zones);
            $multiplier = ZONE_TRUST_MULTIPLIERS[$zone];
            $trustNum = max(1, (int)round($baseTrust * (float)$multiplier));

            [$lowPct, $highPct] = $priceRanges[$dom - 1];
            $priceFloat = bcadd($lowPct, '0', 3) . '-' . bcadd($highPct, '0', 3);

            $numberFloat       = $zoneNumberFloat[$zone];
            $changeNumberFloat = $numberFloat;
            $changeTrustNum    = in_array($dom, $zones['near']) ? 0 : 1;
            $changeSurvival    = in_array($dom, $zones['near']) ? '3-10' : '10-30';

            $configs[] = [
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
            ];
        }
    }

    return $configs;
}

// ==================== SQL 输出 ====================

function generate_sql(array $configs, string $outputPath): void
{
    $dir = dirname($outputPath);
    if (!is_dir($dir)) {
        mkdir($dir, 0755, true);
    }

    $fields = [
        'box_id', 'pid', 'direction', 'dom', 'trust_num',
        'price_float', 'number_float', 'change_trust_num',
        'change_number_float', 'change_survival_time', 'status',
    ];
    $strFields = ['price_float', 'number_float', 'change_number_float', 'change_survival_time'];

    $rows = [];
    foreach ($configs as $c) {
        $parts = [];
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

function pct_to_actual(string $priceFloatPct, string $referencePrice): string
{
    [$lowS, $highS] = explode('-', $priceFloatPct);
    $lowPrice  = bcdiv(bcmul($referencePrice, $lowS), '100', 4);
    $highPrice = bcdiv(bcmul($referencePrice, $highS), '100', 4);
    return "{$lowPrice}-{$highPrice}";
}

function print_header(
    string $symbol,
    string $currentPrice,
    int    $pid,
    int    $levels,
    float  $totalUsdt,
    float  $depthRatio,
    int    $recordCount,
): void {
    $singleSide    = $totalUsdt * $depthRatio / 2;
    $farCoverPct   = $depthRatio * 100 * 10;
    $symbolDisplay = strtoupper(str_replace('_', '/', $symbol));
    $sellCount     = intdiv($recordCount, 2);
    $buyCount      = $recordCount - $sellCount;

    $sep = str_repeat('─', 60);
    echo "\n{$sep}\n";
    echo "  交易对   : {$symbolDisplay}  (参考价格: {$currentPrice})\n";
    echo sprintf("  pid      : %d   档位数: %d   总量: %s USDT\n", $pid, $levels, number_format($totalUsdt, 0));
    echo sprintf("  深度比   : %.1f   远盘覆盖: %.1f%%\n", $depthRatio, $farCoverPct);
    echo sprintf("  单边有效量: %s USDT\n", number_format($singleSide, 0));
    echo "  生成记录 : {$recordCount} 条 ({$sellCount} 卖单 + {$buyCount} 买单)\n";
    echo "{$sep}\n\n";
}

function print_table(array $configs, int $levels, string $referencePrice): void
{
    $sellMap = $buyMap = [];
    foreach ($configs as $c) {
        if ($c['direction'] === -1) $sellMap[$c['dom']] = $c;
        else $buyMap[$c['dom']] = $c;
    }

    $zoneCn = ['near' => '近盘', 'mid' => '中盘', 'far' => '远盘'];

    echo sprintf("%-6s %-6s %6s  %-26s  %-26s\n", '档位', '区域', '委托数', '卖 price_float(%)', '买 price_float(%)');
    echo str_repeat('-', 80) . "\n";

    for ($dom = 1; $dom <= $levels; $dom++) {
        $sc = $sellMap[$dom] ?? [];
        $bc = $buyMap[$dom] ?? [];
        $zoneLabel = $zoneCn[$sc['_zone'] ?? ''] ?? '';
        $trustNum  = $sc['trust_num'] ?? '-';
        $sellPf    = $sc['price_float'] ?? '-';
        $buyPf     = $bc['price_float'] ?? '-';
        echo sprintf("  %-4d %-6s %6s  %-26s  %-26s\n", $dom, $zoneLabel, $trustNum, $sellPf, $buyPf);
    }
    echo "\n";
}

function print_summary(array $configs, string $referencePrice): void
{
    $header = sprintf(
        "%-4s %-4s %-6s %6s %-26s %-22s %-18s %8s %-10s",
        '方向', '档位', '区间', '笔数', '价格区间(%)', '实际价格区间', '数量区间', '变幻委托', '存活时间'
    );
    $sep = str_repeat('-', mb_strlen($header) + 20);

    echo "\n" . str_repeat('=', mb_strlen($header) + 20) . "\n";
    echo " 铺单配置摘要\n";
    echo str_repeat('=', mb_strlen($header) + 20) . "\n";
    echo $header . "\n";
    echo $sep . "\n";

    foreach ($configs as $c) {
        $actual = pct_to_actual($c['price_float'], $referencePrice);
        echo sprintf(
            " %-4s %-4d %-6s %6d %-26s %-22s %-18s %8d %-10s\n",
            $c['_direction_label'],
            $c['dom'],
            ['near' => '近盘', 'mid' => '中盘', 'far' => '远盘'][$c['_zone']] ?? '',
            $c['trust_num'],
            $c['price_float'],
            $actual,
            $c['number_float'],
            $c['change_trust_num'],
            $c['change_survival_time'],
        );
    }

    echo $sep . "\n";
    echo sprintf("共 %d 条配置\n\n", count($configs));
}

// ==================== CLI 入口 ====================

function parse_args(): array
{
    $opts = getopt('', [
        'symbol:', 'pid:', 'levels:', 'total_usdt:', 'depth_ratio:', 'output_dir:',
    ]);

    if (empty($opts['symbol']) || !isset($opts['pid'])) {
        echo <<<USAGE
现货铺单配置生成器 (PHP 版)

用法:
  php generate_box_config.php --symbol eth_usdt --pid 3 --levels 9 \\
      --total_usdt 2000000 --depth_ratio 0.3

参数:
  --symbol       交易对 (必填，如 eth_usdt / btc_usdt)
  --pid          项目 ID (必填)
  --levels       每侧档位数 (默认 6)
  --total_usdt   总量 USDT (默认 1000000)
  --depth_ratio  深度比 (默认 0.2)
  --output_dir   输出目录 (默认 ./output)

USAGE;
        exit(1);
    }

    return [
        'symbol'      => strtolower($opts['symbol']),
        'pid'         => (int)$opts['pid'],
        'levels'      => (int)($opts['levels'] ?? 6),
        'total_usdt'  => (float)($opts['total_usdt'] ?? 1_000_000),
        'depth_ratio' => (float)($opts['depth_ratio'] ?? 0.2),
        'output_dir'  => $opts['output_dir'] ?? 'output',
    ];
}

function main(): void
{
    $args = parse_args();

    $symbol     = $args['symbol'];
    $pid        = $args['pid'];
    $levels     = $args['levels'];
    $totalUsdt  = $args['total_usdt'];
    $depthRatio = $args['depth_ratio'];
    $outputDir  = $args['output_dir'];

    // 1. 拉取币安数据
    echo "[API] 正在获取 " . strtoupper($symbol) . " 行情数据...\n";

    try {
        $currentPrice = get_price($symbol);
        $exchangeInfo = get_exchange_info($symbol);
        $orderBook    = get_order_book($symbol, 20);
    } catch (Throwable $e) {
        fwrite(STDERR, "[错误] 币安 API 请求失败: {$e->getMessage()}\n");
        exit(1);
    }

    echo "[API] 参考价格: {$currentPrice}  tickSize: {$exchangeInfo['tickSize']}\n";

    // 2. 生成配置
    $configs = generate_configs(
        symbol: $symbol,
        levels: $levels,
        totalUsdt: $totalUsdt,
        pid: $pid,
        currentPrice: $currentPrice,
        exchangeInfo: $exchangeInfo,
        orderBook: $orderBook,
    );

    // 3. 输出摘要
    print_header($symbol, $currentPrice, $pid, $levels, $totalUsdt, $depthRatio, count($configs));
    print_table($configs, $levels, $currentPrice);
    print_summary($configs, $currentPrice);

    // 4. 生成 SQL
    $safeSymbol = str_replace('/', '_', $symbol);
    $sqlPath = "{$outputDir}/{$safeSymbol}_pid{$pid}.sql";
    generate_sql($configs, $sqlPath);
}

main();
