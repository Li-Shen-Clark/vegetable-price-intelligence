'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  XAxis,
  YAxis,
} from 'recharts';
import {
  ArrowLeft,
  CalendarClock,
  CheckCircle2,
  CircleAlert,
  CircleGauge,
  Database,
  FlaskConical,
  Gauge,
  Info,
  Route,
  ShieldAlert,
  Target,
  Truck,
} from 'lucide-react';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from '@/components/ui/chart';
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from '@/components/ui/empty';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

type ReleaseStatus =
  | 'model_target'
  | 'model_minimum'
  | 'point_only_model'
  | 'baseline_fallback';

type ProductMetadata = {
  vegetable_id: number;
  vegetable_code: string;
  vegetable_name_zh: string;
  data_file: string;
  snapshot_city_count: number;
  snapshot_record_count: number;
  release_status_by_horizon: Record<string, ReleaseStatus>;
};

type ForecastMetadata = {
  title: string;
  historical_backtest: boolean;
  data_as_of: string;
  snapshot_origin_date: string;
  target_dates: Record<string, string>;
  price_unit: string;
  model_name: string;
  release_status: string;
  release_status_counts: Record<ReleaseStatus, number>;
  overall_final_test: {
    row_count: number;
    model_wape: number;
    baseline_wape: number;
    relative_wape_improvement: number;
    interval_coverage_80: number;
    meets_overall_target_improvement: boolean;
    meets_minimum_7d_14d_product_gate: boolean;
  };
  defaults: { vegetable_id: number; city_id: string; horizon_days: number };
  products: ProductMetadata[];
  status_definitions: Record<ReleaseStatus, string>;
  boundary: string;
};

type City = {
  city_id: string;
  city_name_zh: string;
  province_name_zh: string;
};

type PointMetrics = { wape: number; mae: number; smape: number; row_count: number };
type ProbabilityMetrics = {
  interval_coverage_80: number;
  mean_interval_width: number;
  wis_80: number;
  row_count: number;
};

type Evidence = {
  vegetable_id: number;
  vegetable_name_zh: string;
  horizon_days: number;
  validation_route: string;
  best_baseline: string;
  model_metrics: PointMetrics;
  baseline_metrics: PointMetrics;
  relative_wape_improvement: number;
  improved_series_share: number;
  probability_metrics: ProbabilityMetrics;
  release_status: ReleaseStatus;
  release_point_source: string;
  release_interval: boolean;
};

type ProductPayload = {
  historical_backtest: boolean;
  snapshot_origin_date: string;
  product: {
    vegetable_id: number;
    vegetable_code: string;
    vegetable_name_zh: string;
  };
  cities: City[];
  evidence_by_horizon: Evidence[];
  record_fields: string[];
  records: Array<Array<string | number | null>>;
};

type ForecastRecord = {
  cityId: string;
  horizon: number;
  targetDate: string;
  originPrice: number;
  actualPrice: number;
  baselineName: string;
  baselinePrediction: number;
  modelPrediction: number;
  status: ReleaseStatus;
  pointSource: string;
  releasedPoint: number;
  p10: number | null;
  p90: number | null;
  absolutePercentageError: number;
};

const chartConfig = {
  actualPrice: { label: '实际历史价格', color: 'var(--chart-3)' },
  releasedPoint: { label: '发布点预测', color: 'var(--chart-1)' },
  p10: { label: 'P10', color: 'var(--chart-4)' },
  p90: { label: 'P90', color: 'var(--chart-4)' },
} satisfies ChartConfig;

const statusPresentation: Record<
  ReleaseStatus,
  { label: string; short: string; className: string; description: string }
> = {
  model_target: {
    label: '模型 + 区间 · 达目标',
    short: '达目标',
    className: 'bg-emerald-100 text-emerald-900 hover:bg-emerald-100',
    description: '点预测改善至少 8%，多数城市改善，且区间覆盖通过。',
  },
  model_minimum: {
    label: '模型 + 区间 · 最低可用',
    short: '最低可用',
    className: 'bg-teal-100 text-teal-900 hover:bg-teal-100',
    description: '点预测与区间通过最低门槛，但改善不足 8% 目标线。',
  },
  point_only_model: {
    label: '仅模型点预测',
    short: '仅 P50',
    className: 'bg-amber-100 text-amber-950 hover:bg-amber-100',
    description: '点预测通过，但区间在最终测试中欠校准，因此不发布 P10/P90。',
  },
  baseline_fallback: {
    label: '最佳基线回退',
    short: '基线回退',
    className: 'bg-slate-200 text-slate-900 hover:bg-slate-200',
    description: '模型未通过冻结门槛，发布验证期预先选定的简单基线。',
  },
};

const priceFormatter = new Intl.NumberFormat('zh-CN', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

function formatDate(value: string) {
  const [year, month, day] = value.split('-');
  return `${year}.${month}.${day}`;
}

function readRecords(payload: ProductPayload): ForecastRecord[] {
  return payload.records.map((row) => ({
    cityId: String(row[0]),
    horizon: Number(row[1]),
    targetDate: String(row[2]),
    originPrice: Number(row[3]),
    actualPrice: Number(row[4]),
    baselineName: String(row[5]),
    baselinePrediction: Number(row[6]),
    modelPrediction: Number(row[7]),
    status: String(row[8]) as ReleaseStatus,
    pointSource: String(row[9]),
    releasedPoint: Number(row[10]),
    p10: row[11] === null ? null : Number(row[11]),
    p90: row[12] === null ? null : Number(row[12]),
    absolutePercentageError: Number(row[13]),
  }));
}

function MetricCard({
  label,
  value,
  detail,
  icon,
}: {
  label: string;
  value: string;
  detail: string;
  icon: React.ReactNode;
}) {
  return (
    <Card className="border-0 bg-card/94 shadow-[0_10px_34px_rgb(43_66_54/6%)] ring-1 ring-foreground/8">
      <CardHeader className="grid-cols-[1fr_auto] items-center">
        <CardDescription className="text-[11px] font-semibold uppercase tracking-[0.12em]">
          {label}
        </CardDescription>
        <span className="flex size-8 items-center justify-center rounded-lg bg-primary/8 text-primary">
          {icon}
        </span>
      </CardHeader>
      <CardContent>
        <div className="font-heading text-2xl font-semibold tabular-nums">{value}</div>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">{detail}</p>
      </CardContent>
    </Card>
  );
}

function LoadingSurface() {
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {[0, 1, 2, 3].map((item) => (
          <Card key={item} className="border-0 bg-card/90">
            <CardContent className="space-y-3 pt-4">
              <Skeleton className="h-3 w-24" />
              <Skeleton className="h-8 w-32" />
              <Skeleton className="h-3 w-40" />
            </CardContent>
          </Card>
        ))}
      </div>
      <Skeleton className="h-[420px] w-full rounded-xl" />
    </div>
  );
}

export default function ForecastPage() {
  const [metadata, setMetadata] = useState<ForecastMetadata | null>(null);
  const [payload, setPayload] = useState<ProductPayload | null>(null);
  const [vegetableId, setVegetableId] = useState<number | null>(null);
  const [cityId, setCityId] = useState<string | null>(null);
  const [horizon, setHorizon] = useState(28);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetch('/data/forecast/metadata.json', { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error('metadata');
        return response.json() as Promise<ForecastMetadata>;
      })
      .then((data) => {
        setMetadata(data);
        setVegetableId(data.defaults.vegetable_id);
        setCityId(data.defaults.city_id);
        setHorizon(data.defaults.horizon_days);
      })
      .catch((fetchError: Error) => {
        if (fetchError.name !== 'AbortError') {
          setError('预测回测数据没有载入。请先重新生成 P2 Web 数据，再刷新页面。');
        }
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!metadata || vegetableId === null) return;
    const product = metadata.products.find((item) => item.vegetable_id === vegetableId);
    if (!product) return;
    const controller = new AbortController();
    fetch(`/${product.data_file}`, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error('product');
        return response.json() as Promise<ProductPayload>;
      })
      .then((data) => {
        if (!data.cities.length) throw new Error('empty');
        const defaultExists = data.cities.some(
          (city) => city.city_id === metadata.defaults.city_id,
        );
        setCityId(
          defaultExists ? metadata.defaults.city_id : data.cities[0].city_id,
        );
        setPayload(data);
      })
      .catch((fetchError: Error) => {
        if (fetchError.name !== 'AbortError') {
          setError('当前产品没有可用的回测快照，请更换产品或重新生成数据。');
        }
      });
    return () => controller.abort();
  }, [metadata, vegetableId]);

  const records = useMemo(() => (payload ? readRecords(payload) : []), [payload]);
  const cityMap = useMemo(
    () => new Map(payload?.cities.map((city) => [city.city_id, city]) ?? []),
    [payload],
  );
  const cityRecords = records
    .filter((record) => record.cityId === cityId)
    .sort((a, b) => a.horizon - b.horizon);
  const selectedRecord = cityRecords.find((record) => record.horizon === horizon) ?? null;
  const selectedEvidence =
    payload?.evidence_by_horizon.find((item) => item.horizon_days === horizon) ?? null;
  const currentProduct = metadata?.products.find((item) => item.vegetable_id === vegetableId);
  const currentCity = cityId ? cityMap.get(cityId) : null;
  const selectedStatus = selectedRecord ? statusPresentation[selectedRecord.status] : null;
  const priceChange = selectedRecord
    ? (selectedRecord.releasedPoint / selectedRecord.originPrice - 1) * 100
    : null;

  return (
    <main className="min-h-screen bg-background text-foreground">
      <header className="border-b border-border/70 bg-card/86 backdrop-blur-xl">
        <div className="mx-auto flex w-full max-w-[1500px] flex-col gap-4 px-4 py-5 sm:px-6 lg:flex-row lg:items-center lg:justify-between lg:px-8">
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm">
              <FlaskConical className="size-5" aria-hidden="true" />
            </div>
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-muted-foreground">
                Vegetable Price Intelligence
              </p>
              <h1 className="font-heading text-xl font-semibold tracking-tight sm:text-2xl">
                Forecast Decision Lab
              </h1>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <Link
              href="/"
              className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-background/75 px-3 font-medium text-foreground transition-colors hover:bg-muted"
            >
              <ArrowLeft className="size-3.5" aria-hidden="true" />
              历史监控
            </Link>
            <Link
              href="/alerts"
              className="inline-flex h-8 items-center gap-1.5 rounded-md border border-primary/20 bg-primary/7 px-3 font-medium text-primary transition-colors hover:bg-primary/12"
            >
              <ShieldAlert className="size-3.5" aria-hidden="true" />
              风险预警
            </Link>
            <Link
              href="/procurement"
              className="inline-flex h-8 items-center gap-1.5 rounded-md border border-primary/20 bg-primary/7 px-3 font-medium text-primary transition-colors hover:bg-primary/12"
            >
              <Truck className="size-3.5" aria-hidden="true" />
              采购情景
            </Link>
            <Badge className="bg-amber-100 text-amber-950 hover:bg-amber-100">
              <Database data-icon="inline-start" />
              Historical backtest
            </Badge>
            <span className="rounded-full border border-border bg-background/75 px-3 py-1.5 text-muted-foreground">
              数据截至 {metadata?.data_as_of ?? '2022-06-22'}
            </span>
          </div>
        </div>
      </header>

      <div className="mx-auto w-full max-w-[1500px] px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
        <section aria-labelledby="forecast-controls" className="mb-5">
          <div className="mb-4 flex flex-col gap-2 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-[0.14em] text-primary">
                Frozen test replay · origin 2022.05.01
              </p>
              <h2 id="forecast-controls" className="font-heading text-2xl font-semibold tracking-tight">
                查看预测怎样被接受、降级或回退
              </h2>
              <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">
                这是最后一个历史回测起点的可审计快照。它展示当时能发布什么，并用后来真实发生的价格检验结果；不是当前报价或自动调价建议。
              </p>
            </div>
            {metadata && (
              <div className="flex flex-wrap gap-2 text-xs">
                <Badge variant="outline" className="bg-card/80">
                  模型总体改善 {(metadata.overall_final_test.relative_wape_improvement * 100).toFixed(1)}%
                </Badge>
                <Badge variant="outline" className="bg-card/80">
                  区间覆盖 {(metadata.overall_final_test.interval_coverage_80 * 100).toFixed(1)}%
                </Badge>
              </div>
            )}
          </div>

          <Alert className="mb-4 border-amber-300/70 bg-amber-50/80 text-amber-950">
            <ShieldAlert />
            <AlertTitle>历史回测，不是今天的价格预测</AlertTitle>
            <AlertDescription>
              预测起点固定为 {metadata ? formatDate(metadata.snapshot_origin_date) : '2022.05.01'}；真实结果用于检验模型。pricing engine 仍需成本、利润、库存与业务规则。
            </AlertDescription>
          </Alert>

          <Card className="border-0 bg-[linear-gradient(115deg,var(--card),color-mix(in_oklab,var(--accent)_55%,var(--card)))] py-3 shadow-[0_14px_44px_rgb(43_66_54/7%)] ring-1 ring-foreground/8">
            <CardContent className="grid gap-3 px-3 sm:grid-cols-2 sm:px-4 lg:grid-cols-3">
              <div className="grid gap-1.5 text-xs font-medium text-muted-foreground">
                <span>核心蔬菜</span>
                <Select
                  value={vegetableId === null ? null : String(vegetableId)}
                  onValueChange={(value) => {
                    if (!value) return;
                    setPayload(null);
                    setError(null);
                    setVegetableId(Number(value));
                  }}
                >
                  <SelectTrigger className="h-10! w-full bg-card px-3 text-foreground shadow-xs">
                    <SelectValue>
                      {currentProduct
                        ? `${currentProduct.vegetable_name_zh} · ${currentProduct.vegetable_code}`
                        : '载入产品'}
                    </SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {metadata?.products.map((product) => (
                      <SelectItem key={product.vegetable_id} value={String(product.vegetable_id)}>
                        {product.vegetable_name_zh} · {product.vegetable_code}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="grid gap-1.5 text-xs font-medium text-muted-foreground">
                <span>Tier A 城市</span>
                <Select
                  value={cityId}
                  onValueChange={(value) => value && setCityId(String(value))}
                  disabled={!payload}
                >
                  <SelectTrigger className="h-10! w-full bg-card px-3 text-foreground shadow-xs">
                    <SelectValue>
                      {currentCity
                        ? `${currentCity.city_name_zh} · ${currentCity.province_name_zh}`
                        : '载入城市'}
                    </SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {payload?.cities.map((city) => (
                      <SelectItem key={city.city_id} value={city.city_id}>
                        {city.city_name_zh} · {city.province_name_zh}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="grid gap-1.5 text-xs font-medium text-muted-foreground">
                <span>预测跨度</span>
                <Select
                  value={String(horizon)}
                  onValueChange={(value) => value && setHorizon(Number(value))}
                  disabled={!payload}
                >
                  <SelectTrigger className="h-10! w-full bg-card px-3 text-foreground shadow-xs">
                    <SelectValue>{horizon} 日 · {metadata?.target_dates[String(horizon)] ?? ''}</SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {[7, 14, 28].map((value) => (
                      <SelectItem key={value} value={String(value)}>
                        {value} 日 · 目标 {metadata ? formatDate(metadata.target_dates[String(value)]) : ''}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </CardContent>
          </Card>
        </section>

        {error ? (
          <Alert variant="destructive" className="bg-card py-4">
            <CircleAlert />
            <AlertTitle>预测数据暂时不可用</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : !metadata || !payload ? (
          <LoadingSurface />
        ) : !selectedRecord || !selectedEvidence ? (
          <Empty className="min-h-[360px] border border-border bg-card/90">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <CircleAlert />
              </EmptyMedia>
              <EmptyTitle>这个城市缺少所选跨度</EmptyTitle>
              <EmptyDescription>请选择另一个 Tier A 城市或预测跨度。</EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <section aria-live="polite" aria-busy="false">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <Badge className={selectedStatus?.className}>{selectedStatus?.label}</Badge>
              <span className="text-xs text-muted-foreground">
                路由：{selectedRecord.pointSource.replace('baseline:', '基线 · ')}
              </span>
            </div>

            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <MetricCard
                label="发布点预测"
                value={`¥${priceFormatter.format(selectedRecord.releasedPoint)}/kg`}
                detail={`${priceChange !== null && priceChange >= 0 ? '+' : ''}${priceChange?.toFixed(1)}% vs 起点 ¥${priceFormatter.format(selectedRecord.originPrice)}`}
                icon={<Target className="size-4" aria-hidden="true" />}
              />
              <MetricCard
                label="发布区间"
                value={
                  selectedRecord.p10 !== null && selectedRecord.p90 !== null
                    ? `¥${priceFormatter.format(selectedRecord.p10)}–${priceFormatter.format(selectedRecord.p90)}`
                    : '未发布'
                }
                detail={
                  selectedRecord.p10 !== null
                    ? 'P10–P90 · 80% 目标区间'
                    : selectedRecord.status === 'point_only_model'
                      ? '最终测试覆盖未通过，只保留 P50'
                      : '基线回退不附模型区间'
                }
                icon={<ShieldAlert className="size-4" aria-hidden="true" />}
              />
              <MetricCard
                label="后来实际结果"
                value={`¥${priceFormatter.format(selectedRecord.actualPrice)}/kg`}
                detail={`目标日 ${formatDate(selectedRecord.targetDate)} · 用于回测检验`}
                icon={<CalendarClock className="size-4" aria-hidden="true" />}
              />
              <MetricCard
                label="本次绝对误差"
                value={`${(selectedRecord.absolutePercentageError * 100).toFixed(1)}%`}
                detail={`产品测试 WAPE ${(selectedEvidence.model_metrics.wape * 100).toFixed(1)}%`}
                icon={<CircleGauge className="size-4" aria-hidden="true" />}
              />
            </div>

            <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(320px,0.7fr)]">
              <Card className="border-0 bg-card/94 shadow-[0_18px_54px_rgb(43_66_54/7%)] ring-1 ring-foreground/8">
                <CardHeader className="border-b border-border/65 pb-4">
                  <CardTitle className="text-lg">
                    {currentProduct?.vegetable_name_zh} · {currentCity?.city_name_zh} 三个跨度回放
                  </CardTitle>
                  <CardDescription>
                    比较冻结发布点预测与后来实际价格；区间只在发布矩阵允许时显示。
                  </CardDescription>
                </CardHeader>
                <CardContent className="pt-4">
                  <ChartContainer config={chartConfig} className="h-[360px] w-full aspect-auto">
                    <LineChart data={cityRecords} margin={{ left: 2, right: 12, top: 16, bottom: 0 }}>
                      <CartesianGrid vertical={false} strokeDasharray="3 5" />
                      <XAxis
                        dataKey="horizon"
                        axisLine={false}
                        tickLine={false}
                        tickFormatter={(value) => `${value}日`}
                      />
                      <YAxis
                        axisLine={false}
                        tickLine={false}
                        tickMargin={8}
                        width={52}
                        tickFormatter={(value) => `¥${Number(value).toFixed(1)}`}
                        domain={['auto', 'auto']}
                      />
                      <ChartTooltip
                        content={
                          <ChartTooltipContent
                            labelFormatter={(value) => `${value} 日预测跨度`}
                          />
                        }
                      />
                      <ReferenceLine x={horizon} stroke="var(--border)" strokeDasharray="3 3" />
                      <Line
                        dataKey="actualPrice"
                        type="monotone"
                        stroke="var(--color-actualPrice)"
                        strokeWidth={2.4}
                        dot={{ r: 4 }}
                        isAnimationActive={false}
                      />
                      <Line
                        dataKey="releasedPoint"
                        type="monotone"
                        stroke="var(--color-releasedPoint)"
                        strokeWidth={2.4}
                        strokeDasharray="5 4"
                        dot={{ r: 4 }}
                        isAnimationActive={false}
                      />
                      <Line
                        dataKey="p10"
                        type="monotone"
                        stroke="var(--color-p10)"
                        strokeWidth={1.4}
                        dot={{ r: 3 }}
                        connectNulls={false}
                        isAnimationActive={false}
                      />
                      <Line
                        dataKey="p90"
                        type="monotone"
                        stroke="var(--color-p90)"
                        strokeWidth={1.4}
                        dot={{ r: 3 }}
                        connectNulls={false}
                        isAnimationActive={false}
                      />
                    </LineChart>
                  </ChartContainer>
                </CardContent>
              </Card>

              <Card className="border-0 bg-card/94 shadow-[0_18px_54px_rgb(43_66_54/7%)] ring-1 ring-foreground/8">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-lg">
                    <Route className="size-4 text-primary" aria-hidden="true" />
                    为什么这样路由
                  </CardTitle>
                  <CardDescription>{selectedStatus?.description}</CardDescription>
                </CardHeader>
                <CardContent className="space-y-4 text-sm">
                  <div className="rounded-lg bg-muted/70 p-3">
                    <p className="text-xs font-medium text-muted-foreground">冻结测试证据</p>
                    <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-2 tabular-nums">
                      <dt className="text-muted-foreground">模型 WAPE</dt>
                      <dd className="text-right font-medium">{(selectedEvidence.model_metrics.wape * 100).toFixed(2)}%</dd>
                      <dt className="text-muted-foreground">基线 WAPE</dt>
                      <dd className="text-right font-medium">{(selectedEvidence.baseline_metrics.wape * 100).toFixed(2)}%</dd>
                      <dt className="text-muted-foreground">相对改善</dt>
                      <dd className="text-right font-medium">{(selectedEvidence.relative_wape_improvement * 100).toFixed(2)}%</dd>
                      <dt className="text-muted-foreground">改善城市</dt>
                      <dd className="text-right font-medium">{(selectedEvidence.improved_series_share * 100).toFixed(1)}%</dd>
                      <dt className="text-muted-foreground">区间覆盖</dt>
                      <dd className="text-right font-medium">{(selectedEvidence.probability_metrics.interval_coverage_80 * 100).toFixed(1)}%</dd>
                      <dt className="text-muted-foreground">最佳基线</dt>
                      <dd className="text-right font-medium">{selectedEvidence.best_baseline}</dd>
                    </dl>
                  </div>
                  <div className="flex gap-2 rounded-lg border border-border p-3 text-xs leading-5 text-muted-foreground">
                    <Info className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden="true" />
                    <p>
                      最终测试只接受、降级或拒绝已冻结规格。即使某个 validation 回退切片后来表现变好，也不会用测试结果反向晋升。
                    </p>
                  </div>
                </CardContent>
              </Card>
            </div>

            <Card className="mt-4 border-0 bg-card/94 shadow-[0_18px_54px_rgb(43_66_54/7%)] ring-1 ring-foreground/8">
              <CardHeader>
                <CardTitle className="text-lg">同一城市的完整发布路径</CardTitle>
                <CardDescription>
                  P50 始终显示最终可发布的点估计；P10/P90 只在区间通过时显示。
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="overflow-x-auto rounded-lg border border-border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>跨度</TableHead>
                        <TableHead>目标日</TableHead>
                        <TableHead className="text-right">发布点</TableHead>
                        <TableHead className="text-right">实际值</TableHead>
                        <TableHead className="text-right">绝对误差</TableHead>
                        <TableHead>发布状态</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {cityRecords.map((record) => (
                        <TableRow key={record.horizon} className={record.horizon === horizon ? 'bg-primary/5' : ''}>
                          <TableCell className="font-medium">{record.horizon} 日</TableCell>
                          <TableCell>{formatDate(record.targetDate)}</TableCell>
                          <TableCell className="text-right tabular-nums">¥{priceFormatter.format(record.releasedPoint)}</TableCell>
                          <TableCell className="text-right tabular-nums">¥{priceFormatter.format(record.actualPrice)}</TableCell>
                          <TableCell className="text-right tabular-nums">{(record.absolutePercentageError * 100).toFixed(1)}%</TableCell>
                          <TableCell>
                            <Badge className={statusPresentation[record.status].className}>
                              {statusPresentation[record.status].short}
                            </Badge>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </CardContent>
            </Card>

            <div className="mt-4 grid gap-4 lg:grid-cols-3">
              <Card className="border-0 bg-primary text-primary-foreground shadow-[0_18px_54px_rgb(43_66_54/10%)] lg:col-span-2">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-lg">
                    <CheckCircle2 className="size-5" aria-hidden="true" />
                    它怎样补充 pricing engine
                  </CardTitle>
                </CardHeader>
                <CardContent className="grid gap-3 text-sm leading-6 text-primary-foreground/85 sm:grid-cols-3">
                  <div>
                    <p className="font-semibold text-primary-foreground">预测层</p>
                    <p>给出未来价格方向、幅度与不确定性。</p>
                  </div>
                  <div>
                    <p className="font-semibold text-primary-foreground">决策层</p>
                    <p>pricing engine 结合成本、库存、利润和规则形成报价。</p>
                  </div>
                  <div>
                    <p className="font-semibold text-primary-foreground">控制层</p>
                    <p>失败切片自动降级，不把低可信区间传给业务。</p>
                  </div>
                </CardContent>
              </Card>
              <Card className="border-0 bg-card/94 ring-1 ring-foreground/8">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-lg">
                    <Gauge className="size-4 text-primary" aria-hidden="true" />
                    全局不是“通过”
                  </CardTitle>
                </CardHeader>
                <CardContent className="text-sm leading-6 text-muted-foreground">
                  总体改善只有 {(metadata.overall_final_test.relative_wape_improvement * 100).toFixed(1)}%，低于 8%；7 日产品门槛和总体区间覆盖也未通过。因此产品采用部分发布，而不是隐藏失败结果。
                </CardContent>
              </Card>
            </div>
          </section>
        )}
      </div>
    </main>
  );
}
