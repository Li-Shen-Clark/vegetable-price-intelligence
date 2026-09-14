'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { CartesianGrid, Line, LineChart, ReferenceLine, XAxis, YAxis } from 'recharts';
import {
  ArrowLeft,
  BriefcaseBusiness,
  Building2,
  CircleAlert,
  CircleGauge,
  Database,
  FlaskConical,
  Info,
  Radar,
  ShieldCheck,
  Siren,
  TrendingDown,
  Truck,
  Waves,
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
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';

type WindowOption = { id: string; label: string; splits: string[] };

type Product = {
  vegetable_id: number;
  vegetable_code: string;
  vegetable_name_zh: string;
  data_file: string;
  city_count: number;
  common_shock_bins: number;
  validation_edges: number;
  final_confirmed_edges: number;
};

type Metadata = {
  title: string;
  historical_only: boolean;
  data_as_of: string;
  release_status: 'common_shock_only';
  directional_network_released: false;
  release_message: string;
  defaults: { vegetable_id: number; window_id: string; city_id: string };
  windows: WindowOption[];
  products: Product[];
  evidence_funnel: Array<{ label: string; count: number }>;
  release_metrics: {
    frozen_edges: number;
    final_confirmed_edges: number;
    final_strong_edges: number;
    positive_final_edge_share: number;
    median_final_rmse_improvement: number;
    qualifying_products: number;
  };
  common_factor_diagnostic: {
    raw_fdr_edges: number;
    common_factor_adjusted_fdr_edges: number;
    edge_reduction_share: number;
  };
  exposure_score_formula: string;
  pricing_action: string;
  boundary: string;
};

type ProductPayload = {
  historical_only: boolean;
  release_status: 'common_shock_only';
  directional_edges_included: false;
  positive_common_shock_threshold: number;
  timeline_fields: string[];
  timeline: Array<Array<string | number | boolean>>;
  exposure_fields: string[];
  city_exposures: Array<Array<string | number | null>>;
};

type TimelineRow = {
  binStart: string;
  split: string;
  commonFactor: number;
  commonFactorPct: number;
  adjustedReturnPct: number;
  exposedCityCount: number;
  observedCityCount: number;
  positiveCommonShock: boolean;
};

type ExposureRow = {
  windowId: string;
  cityId: string;
  cityName: string;
  provinceName: string;
  observedBins: number;
  positiveShocks: number;
  shockRate: number;
  commonBeta: number;
  commonCorrelation: number;
  residualVolatility: number;
  reliability: number;
  latestPrice: number;
  exposureScore: number;
  exposureRank: number;
};

const chartConfig = {
  commonFactorPct: { label: '共同价格变化', color: 'var(--chart-1)' },
  adjustedReturnPct: { label: '城市中位变化', color: 'var(--chart-2)' },
} satisfies ChartConfig;

const percentFormatter = new Intl.NumberFormat('zh-CN', {
  style: 'percent',
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});

const numberFormatter = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 1 });

function readTimeline(payload: ProductPayload): TimelineRow[] {
  return payload.timeline.map((row) => ({
    binStart: String(row[0]),
    split: String(row[1]),
    commonFactor: Number(row[2]),
    commonFactorPct: Number(row[2]) * 100,
    adjustedReturnPct: Number(row[3]) * 100,
    exposedCityCount: Number(row[4]),
    observedCityCount: Number(row[5]),
    positiveCommonShock: Boolean(row[6]),
  }));
}

function readExposures(payload: ProductPayload): ExposureRow[] {
  return payload.city_exposures.map((row) => ({
    windowId: String(row[0]),
    cityId: String(row[1]),
    cityName: String(row[2]),
    provinceName: String(row[3]),
    observedBins: Number(row[4]),
    positiveShocks: Number(row[5]),
    shockRate: Number(row[6]),
    commonBeta: Number(row[7]),
    commonCorrelation: Number(row[8]),
    residualVolatility: Number(row[9]),
    reliability: Number(row[10]),
    latestPrice: Number(row[11]),
    exposureScore: Number(row[12]),
    exposureRank: Number(row[13]),
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
    <Card className="border-0 bg-card/92 shadow-[0_10px_34px_rgb(43_66_54/6%)] ring-1 ring-foreground/8">
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
              <Skeleton className="h-8 w-28" />
              <Skeleton className="h-3 w-40" />
            </CardContent>
          </Card>
        ))}
      </div>
      <Skeleton className="h-[360px] w-full rounded-xl" />
    </div>
  );
}

export default function PropagationPage() {
  const [metadata, setMetadata] = useState<Metadata | null>(null);
  const [payload, setPayload] = useState<ProductPayload | null>(null);
  const [vegetableId, setVegetableId] = useState<number | null>(null);
  const [windowId, setWindowId] = useState('final_test');
  const [cityId, setCityId] = useState('all');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetch('/data/propagation/metadata.json', { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error('metadata');
        return response.json() as Promise<Metadata>;
      })
      .then((data) => {
        setMetadata(data);
        setVegetableId(data.defaults.vegetable_id);
        setWindowId(data.defaults.window_id);
        setCityId(data.defaults.city_id);
      })
      .catch((fetchError: Error) => {
        if (fetchError.name !== 'AbortError') {
          setError('P5 共同冲击数据没有载入。请先重新生成本地浏览器数据。');
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
        setPayload(data);
        setCityId('all');
      })
      .catch((fetchError: Error) => {
        if (fetchError.name !== 'AbortError') {
          setError('当前产品的共同冲击数据不可用，请更换产品或重建 P5 数据。');
        }
      });
    return () => controller.abort();
  }, [metadata, vegetableId]);

  const timeline = useMemo(() => (payload ? readTimeline(payload) : []), [payload]);
  const exposures = useMemo(() => (payload ? readExposures(payload) : []), [payload]);
  const selectedWindow = metadata?.windows.find((item) => item.id === windowId) ?? null;
  const windowTimeline = useMemo(
    () => timeline.filter((row) => selectedWindow?.splits.includes(row.split)),
    [selectedWindow, timeline],
  );
  const windowExposures = useMemo(
    () => exposures.filter((row) => row.windowId === windowId).sort((a, b) => a.exposureRank - b.exposureRank),
    [exposures, windowId],
  );
  const selectedExposure =
    cityId === 'all' ? windowExposures[0] : windowExposures.find((row) => row.cityId === cityId);
  const tableRows = cityId === 'all' ? windowExposures.slice(0, 10) : windowExposures.filter((row) => row.cityId === cityId);
  const commonShockCount = windowTimeline.filter((row) => row.positiveCommonShock).length;
  const peakCommonShock = [...windowTimeline].sort((left, right) => right.commonFactor - left.commonFactor)[0];
  const thresholdPct = (payload?.positive_common_shock_threshold ?? 0) * 100;

  return (
    <main className="min-h-screen bg-background text-foreground">
      <header className="border-b border-border/70 bg-card/86 backdrop-blur-xl">
        <div className="mx-auto flex w-full max-w-[1500px] flex-col gap-4 px-4 py-5 sm:px-6 lg:flex-row lg:items-center lg:justify-between lg:px-8">
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm">
              <Waves className="size-5" aria-hidden="true" />
            </div>
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-muted-foreground">
                Vegetable Price Intelligence
              </p>
              <h1 className="font-heading text-xl font-semibold tracking-tight sm:text-2xl">
                Common Shock & City Exposure
              </h1>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <Link href="/case-study" className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-background/75 px-3 font-medium transition-colors hover:bg-muted">
              <BriefcaseBusiness className="size-3.5" aria-hidden="true" /> Case Study
            </Link>
            <Link href="/" className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-background/75 px-3 font-medium transition-colors hover:bg-muted">
              <ArrowLeft className="size-3.5" aria-hidden="true" /> 历史监控
            </Link>
            <Link href="/forecast" className="inline-flex h-8 items-center gap-1.5 rounded-md border border-primary/20 bg-primary/7 px-3 font-medium text-primary transition-colors hover:bg-primary/12">
              <FlaskConical className="size-3.5" aria-hidden="true" /> 预测实验
            </Link>
            <Link href="/alerts" className="inline-flex h-8 items-center gap-1.5 rounded-md border border-primary/20 bg-primary/7 px-3 font-medium text-primary transition-colors hover:bg-primary/12">
              <Siren className="size-3.5" aria-hidden="true" /> 风险预警
            </Link>
            <Link href="/procurement" className="inline-flex h-8 items-center gap-1.5 rounded-md border border-primary/20 bg-primary/7 px-3 font-medium text-primary transition-colors hover:bg-primary/12">
              <Truck className="size-3.5" aria-hidden="true" /> 采购情景
            </Link>
            <Badge className="bg-amber-100 text-amber-950 hover:bg-amber-100">
              <Database data-icon="inline-start" /> 历史研究 · Historical
            </Badge>
          </div>
        </div>
      </header>

      <div className="mx-auto w-full max-w-[1500px] px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
        <section className="mb-5" aria-labelledby="propagation-controls">
          <div className="mb-4 flex flex-col gap-2 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-[0.14em] text-primary">
                P5 · 共同冲击 → 城市暴露 → Pricing 人工复核
              </p>
              <h2 id="propagation-controls" className="font-heading text-2xl font-semibold tracking-tight">
                先识别系统性价格压力，再决定复核范围
              </h2>
              <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">
                全国共同供给、天气与季节变化可能让多城同步涨价。本页剔除共同成分后审计方向关系，并只把经得住 final test 的证据交给产品。
              </p>
            </div>
            <div className="flex flex-wrap gap-2 text-xs">
              <Badge variant="outline" className="bg-card/80">10 种核心蔬菜</Badge>
              <Badge variant="outline" className="bg-card/80">3 日频主分析</Badge>
              <Badge variant="outline" className="bg-card/80">数据截至 {metadata?.data_as_of ?? '2022-06-22'}</Badge>
            </div>
          </div>

          <Alert className="mb-4 border-amber-300/70 bg-amber-50 text-amber-950">
            <CircleAlert />
            <AlertTitle>发布状态：共同冲击与城市暴露</AlertTitle>
            <AlertDescription className="space-y-1.5">
              <p>{metadata?.release_message ?? '方向 lead-lag 未通过跨产品 final-test 门槛；当前只发布共同冲击与城市暴露。'}</p>
              <p className="font-medium">方向网络未发布：页面不显示传播中心、来源—目标边或预计传播路径。</p>
            </AlertDescription>
          </Alert>

          <Card className="border-0 bg-[linear-gradient(115deg,var(--card),color-mix(in_oklab,var(--accent)_55%,var(--card)))] py-3 shadow-[0_14px_44px_rgb(43_66_54/7%)] ring-1 ring-foreground/8">
            <CardContent className="grid gap-3 px-3 sm:grid-cols-2 sm:px-4 lg:grid-cols-3">
              <label className="grid gap-1.5 text-xs font-medium text-muted-foreground">
                核心蔬菜
                <NativeSelect value={vegetableId ?? ''} onChange={(event) => setVegetableId(Number(event.target.value))}>
                  {metadata?.products.map((product) => (
                    <NativeSelectOption key={product.vegetable_id} value={product.vegetable_id}>
                      {product.vegetable_name_zh} · {product.vegetable_code}
                    </NativeSelectOption>
                  ))}
                </NativeSelect>
              </label>
              <label className="grid gap-1.5 text-xs font-medium text-muted-foreground">
                历史窗口
                <NativeSelect value={windowId} onChange={(event) => { setWindowId(event.target.value); setCityId('all'); }}>
                  {metadata?.windows.map((window) => (
                    <NativeSelectOption key={window.id} value={window.id}>{window.label}</NativeSelectOption>
                  ))}
                </NativeSelect>
              </label>
              <label className="grid gap-1.5 text-xs font-medium text-muted-foreground">
                城市暴露
                <NativeSelect value={cityId} onChange={(event) => setCityId(event.target.value)} disabled={!payload}>
                  <NativeSelectOption value="all">全部城市 · 显示 Top 10</NativeSelectOption>
                  {windowExposures.map((city) => (
                    <NativeSelectOption key={city.cityId} value={city.cityId}>
                      #{city.exposureRank} {city.cityName} · {city.provinceName}
                    </NativeSelectOption>
                  ))}
                </NativeSelect>
              </label>
            </CardContent>
          </Card>
        </section>

        {error ? (
          <Alert variant="destructive"><CircleAlert /><AlertTitle>数据暂时不可用</AlertTitle><AlertDescription>{error}</AlertDescription></Alert>
        ) : !metadata || !payload ? (
          <LoadingSurface />
        ) : !windowTimeline.length || !windowExposures.length ? (
          <Empty className="border border-dashed bg-card/70">
            <EmptyHeader><EmptyMedia variant="icon"><Radar /></EmptyMedia><EmptyTitle>当前筛选没有历史证据</EmptyTitle><EmptyDescription>请选择另一个产品或历史窗口。</EmptyDescription></EmptyHeader>
          </Empty>
        ) : (
          <section className="space-y-4" aria-label="共同冲击分析结果">
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <MetricCard label="共同冲击箱" value={`${commonShockCount}`} detail={`${selectedWindow?.label} · 超过训练期 P95`} icon={<Waves className="size-4" />} />
              <MetricCard label="最高共同涨幅" value={`${numberFormatter.format((peakCommonShock?.commonFactor ?? 0) * 100)}%`} detail={peakCommonShock?.binStart ?? '—'} icon={<CircleGauge className="size-4" />} />
              <MetricCard label="最高城市暴露" value={selectedExposure ? `${numberFormatter.format(selectedExposure.exposureScore)} / 100` : '—'} detail={selectedExposure ? `#${selectedExposure.exposureRank} · ${selectedExposure.cityName}` : '描述性排名'} icon={<Building2 className="size-4" />} />
              <MetricCard label="共同因子校正" value={`−${percentFormatter.format(metadata.common_factor_diagnostic.edge_reduction_share)}`} detail="训练期同步 FDR 关系减少" icon={<TrendingDown className="size-4" />} />
            </div>

            <div className="grid gap-4 xl:grid-cols-[1.55fr_0.85fr]">
              <Card className="border-0 bg-card/92 ring-1 ring-foreground/8">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2"><Waves className="size-4 text-primary" /> 共同价格变化时间线</CardTitle>
                  <CardDescription>产品内其他 Tier A 城市的 leave-one-out 中位变化；虚线为训练期正向 P95 阈值。</CardDescription>
                </CardHeader>
                <CardContent>
                  <ChartContainer config={chartConfig} className="h-[330px] w-full">
                    <LineChart data={windowTimeline} margin={{ left: 4, right: 14, top: 8, bottom: 4 }}>
                      <CartesianGrid vertical={false} strokeDasharray="3 3" />
                      <XAxis dataKey="binStart" minTickGap={42} tickFormatter={(value) => String(value).slice(0, 7)} />
                      <YAxis tickFormatter={(value) => `${Number(value).toFixed(0)}%`} width={48} />
                      <ChartTooltip content={<ChartTooltipContent labelFormatter={(value) => String(value)} />} />
                      <ReferenceLine y={thresholdPct} stroke="var(--chart-3)" strokeDasharray="5 5" />
                      <ReferenceLine y={0} stroke="var(--border)" />
                      <Line type="monotone" dataKey="commonFactorPct" stroke="var(--color-commonFactorPct)" strokeWidth={1.8} dot={false} isAnimationActive={false} />
                    </LineChart>
                  </ChartContainer>
                  <p className="mt-2 text-xs leading-5 text-muted-foreground">图中上行表示多城共同价格压力增强，不代表某个城市导致其他城市涨价。</p>
                </CardContent>
              </Card>

              <Card className="border-0 bg-card/92 ring-1 ring-foreground/8">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2"><ShieldCheck className="size-4 text-primary" /> 证据漏斗</CardTitle>
                  <CardDescription>每一道门槛都在下一阶段前冻结，final test 只使用一次。</CardDescription>
                </CardHeader>
                <CardContent className="space-y-3">
                  {metadata.evidence_funnel.map((stage, index) => {
                    const maximum = metadata.evidence_funnel[0]?.count ?? 1;
                    const width = stage.count === 0 ? 0 : Math.max(4, (stage.count / maximum) * 100);
                    return (
                      <div key={stage.label}>
                        <div className="mb-1 flex items-center justify-between gap-3 text-xs">
                          <span className="text-muted-foreground">{index + 1}. {stage.label}</span>
                          <span className="font-mono font-semibold tabular-nums">{stage.count}</span>
                        </div>
                        <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                          <div className="h-full rounded-full bg-primary" style={{ width: `${width}%` }} />
                        </div>
                      </div>
                    );
                  })}
                  <Alert className="border-border bg-muted/55"><Info /><AlertTitle>为什么终点是 0？</AlertTitle><AlertDescription>4/15 边在 final test 改善为正，但跨产品覆盖、70% 正增益占比与 1% 中位增益均未通过，所以不展示任何方向边。</AlertDescription></Alert>
                </CardContent>
              </Card>
            </div>

            <Card className="border-0 bg-card/92 ring-1 ring-foreground/8">
              <CardHeader>
                <CardTitle className="flex items-center gap-2"><Building2 className="size-4 text-primary" /> 城市历史暴露排名</CardTitle>
                <CardDescription>{metadata.exposure_score_formula}。分数是同产品、同窗口的描述性指数，不是概率。</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="overflow-x-auto rounded-lg border border-border/80">
                  <Table>
                    <TableHeader><TableRow><TableHead>城市</TableHead><TableHead className="text-right">暴露分数</TableHead><TableHead className="text-right">残差冲击率</TableHead><TableHead className="text-right">共同因子 β</TableHead><TableHead className="text-right">残差波动</TableHead><TableHead className="text-right">数据可靠性</TableHead><TableHead>Pricing 动作</TableHead></TableRow></TableHeader>
                    <TableBody>
                      {tableRows.map((row) => (
                        <TableRow key={row.cityId}>
                          <TableCell><div className="font-medium">#{row.exposureRank} · {row.cityName}</div><div className="text-[11px] text-muted-foreground">{row.provinceName} · {row.observedBins} 个有效箱</div></TableCell>
                          <TableCell className="text-right font-mono font-semibold">{numberFormatter.format(row.exposureScore)}</TableCell>
                          <TableCell className="text-right tabular-nums">{percentFormatter.format(row.shockRate)}</TableCell>
                          <TableCell className="text-right tabular-nums">{numberFormatter.format(row.commonBeta)}</TableCell>
                          <TableCell className="text-right tabular-nums">{percentFormatter.format(row.residualVolatility)}</TableCell>
                          <TableCell className="text-right tabular-nums">{percentFormatter.format(row.reliability)}</TableCell>
                          <TableCell><Badge variant="outline" className="bg-primary/5 text-primary">成本与报价复核</Badge></TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </CardContent>
            </Card>

            <div className="grid gap-4 lg:grid-cols-3">
              <Card className="border-0 bg-muted/70 ring-1 ring-foreground/7"><CardHeader><CardTitle className="text-base">经济学机制</CardTitle></CardHeader><CardContent className="text-sm leading-6 text-muted-foreground">空间套利、信息扩散与共同供给冲击都可能形成跨城共振；leave-one-out 共同因子先隔离全国同步变化，再检验来源滞后是否增加预测力。</CardContent></Card>
              <Card className="border-0 bg-muted/70 ring-1 ring-foreground/7"><CardHeader><CardTitle className="text-base">Pricing 接口</CardTitle></CardHeader><CardContent className="text-sm leading-6 text-muted-foreground">{metadata.pricing_action} 当共同压力上升或城市暴露靠前时，团队应复核成本基准、毛利和替代来源，而不是直接改价。该信号不是价格建议或自动调价触发器。</CardContent></Card>
              <Card className="border-0 bg-muted/70 ring-1 ring-foreground/7"><CardHeader><CardTitle className="text-base">识别边界</CardTitle></CardHeader><CardContent className="text-sm leading-6 text-muted-foreground">{metadata.boundary}</CardContent></Card>
            </div>
          </section>
        )}
      </div>
    </main>
  );
}
