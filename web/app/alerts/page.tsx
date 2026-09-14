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
  BellRing,
  CalendarDays,
  CheckCircle2,
  CircleAlert,
  CircleGauge,
  Database,
  FlaskConical,
  Gauge,
  MapPinned,
  ShieldCheck,
  Siren,
  Target,
  TimerReset,
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

type ReleaseStatus = 'alert_release' | 'research_only' | 'no_signal';

type ProductMetadata = {
  vegetable_id: number;
  vegetable_code: string;
  vegetable_name_zh: string;
  data_file: string;
  city_count: number;
  origin_count: number;
  row_count: number;
  event_count: number;
  predicted_alert_count: number;
  average_precision: number;
  recall_at_frozen_threshold: number;
};

type AlertMetadata = {
  title: string;
  historical_replay: boolean;
  data_period: { start: string; end: string; source_end: string };
  event_definition: string;
  model_name: string;
  release_status: ReleaseStatus;
  action_threshold: number;
  overall: {
    rows: number;
    events: number;
    prevalence: number;
    average_precision: number;
    best_baseline_average_precision: number;
    average_precision_lift_vs_baseline: number;
    precision: number;
    recall: number;
    false_positive_rate: number;
    false_alert_share: number;
    true_positives: number;
    mean_lead_days: number;
    top_decile_spike_recall: number;
  };
  defaults: { vegetable_id: number; city_id: string; origin_date: string };
  products: ProductMetadata[];
  pr_curve: Array<{
    threshold: number;
    precision: number;
    recall: number;
    false_positive_rate: number;
  }>;
  status_definition: Record<ReleaseStatus, string>;
  boundary: string;
};

type City = {
  city_id: string;
  city_name_zh: string;
  province_name_zh: string;
};

type SliceMetrics = {
  rows: number;
  events: number;
  prevalence: number;
  average_precision: number;
  brier_score: number;
  at_frozen_validation_threshold: {
    true_positives: number;
    false_positives: number;
    false_negatives: number;
    true_negatives: number;
    alerts: number;
    precision: number;
    recall: number;
    false_positive_rate: number;
    false_alert_share: number;
  };
};

type ProductPayload = {
  historical_replay: boolean;
  product: {
    vegetable_id: number;
    vegetable_code: string;
    vegetable_name_zh: string;
  };
  release_status: ReleaseStatus;
  metrics: SliceMetrics;
  cities: City[];
  origins: string[];
  record_fields: string[];
  records: Array<Array<string | number | boolean | null>>;
};

type AlertRecord = {
  cityId: string;
  originDate: string;
  originPrice: number;
  riskProbability: number;
  actionThreshold: number;
  predictedAlert: boolean;
  eventLabel: boolean;
  futurePeakPrice: number;
  futurePeakDate: string;
  futurePeakReturn: number;
  eventLeadDays: number | null;
  outcomeType: string;
  severity: string;
  eventScope: string;
  regionalRawEventShare: number;
  originQuality: string;
  originFillDays: number;
  effectiveReturnThreshold: number;
  baselineRiskScore: number;
  staleShare: number;
  outlierShare: number;
};

const riskChartConfig = {
  riskProbability: { label: '模型风险概率', color: 'var(--chart-3)' },
  eventPoint: { label: '实际事件', color: 'var(--destructive)' },
} satisfies ChartConfig;

const prChartConfig = {
  precision: { label: 'Precision', color: 'var(--chart-1)' },
} satisfies ChartConfig;

const percentFormatter = new Intl.NumberFormat('zh-CN', {
  style: 'percent',
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});

const priceFormatter = new Intl.NumberFormat('zh-CN', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

function formatDate(value: string) {
  const [year, month, day] = value.split('-');
  return `${year}.${month}.${day}`;
}

function formatAxisDate(value: string) {
  const [, month, day] = value.split('-');
  return `${Number(month)}/${Number(day)}`;
}

function readRecords(payload: ProductPayload): AlertRecord[] {
  return payload.records.map((row) => ({
    cityId: String(row[0]),
    originDate: String(row[1]),
    originPrice: Number(row[2]),
    riskProbability: Number(row[3]),
    actionThreshold: Number(row[4]),
    predictedAlert: Boolean(row[5]),
    eventLabel: Boolean(row[6]),
    futurePeakPrice: Number(row[7]),
    futurePeakDate: String(row[8]),
    futurePeakReturn: Number(row[9]),
    eventLeadDays: row[10] === null ? null : Number(row[10]),
    outcomeType: String(row[11]),
    severity: String(row[12]),
    eventScope: String(row[13]),
    regionalRawEventShare: Number(row[14]),
    originQuality: String(row[15]),
    originFillDays: Number(row[16]),
    effectiveReturnThreshold: Number(row[17]),
    baselineRiskScore: Number(row[18]),
    staleShare: Number(row[19]),
    outlierShare: Number(row[20]),
  }));
}

const outcomePresentation: Record<
  string,
  { label: string; className: string; detail: string }
> = {
  true_positive: {
    label: '命中事件',
    className: 'bg-emerald-100 text-emerald-900 hover:bg-emerald-100',
    detail: '模型发出提醒，随后发生了冻结定义中的显著涨价事件。',
  },
  false_positive: {
    label: '误报',
    className: 'bg-amber-100 text-amber-950 hover:bg-amber-100',
    detail: '模型发出提醒，但随后没有形成去重后的正式事件。',
  },
  false_negative: {
    label: '漏报',
    className: 'bg-rose-100 text-rose-900 hover:bg-rose-100',
    detail: '随后发生正式事件，但冻结阈值没有触发提醒。',
  },
  true_negative: {
    label: '正常未报',
    className: 'bg-slate-200 text-slate-900 hover:bg-slate-200',
    detail: '模型没有发出提醒，随后也没有形成正式事件。',
  },
};

const severityLabels: Record<string, string> = {
  below_20pct: '低于20%',
  elevated: '显著（20%–50%）',
  high: '高（50%–100%）',
  extreme: '极端（≥100%）',
};

const scopeLabels: Record<string, string> = {
  local: '局部',
  multi_city: '多城市',
  regional: '区域性',
};

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

export default function AlertsPage() {
  const [metadata, setMetadata] = useState<AlertMetadata | null>(null);
  const [payload, setPayload] = useState<ProductPayload | null>(null);
  const [vegetableId, setVegetableId] = useState<number | null>(null);
  const [cityId, setCityId] = useState<string | null>(null);
  const [originDate, setOriginDate] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetch('/data/alerts/metadata.json', { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error('metadata');
        return response.json() as Promise<AlertMetadata>;
      })
      .then((data) => {
        setMetadata(data);
        setVegetableId(data.defaults.vegetable_id);
        setCityId(data.defaults.city_id);
        setOriginDate(data.defaults.origin_date);
      })
      .catch((fetchError: Error) => {
        if (fetchError.name !== 'AbortError') {
          setError('预警历史回放数据没有载入。请先重新生成 P3 Web 数据，再刷新页面。');
        }
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!metadata || vegetableId === null) return;
    const product = metadata.products.find((item) => item.vegetable_id === vegetableId);
    if (!product) return;
    const controller = new AbortController();
    setPayload(null);
    fetch(`/${product.data_file}`, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error('product');
        return response.json() as Promise<ProductPayload>;
      })
      .then((data) => {
        const parsed = readRecords(data);
        const defaultRecord = parsed.find(
          (record) =>
            data.product.vegetable_id === metadata.defaults.vegetable_id &&
            record.cityId === metadata.defaults.city_id &&
            record.originDate === metadata.defaults.origin_date,
        );
        const fallback =
          parsed
            .filter((record) => record.outcomeType === 'true_positive')
            .sort((a, b) => b.riskProbability - a.riskProbability)[0] ??
          parsed.sort((a, b) => b.originDate.localeCompare(a.originDate))[0];
        const selection = defaultRecord ?? fallback;
        setCityId(selection.cityId);
        setOriginDate(selection.originDate);
        setPayload(data);
      })
      .catch((fetchError: Error) => {
        if (fetchError.name !== 'AbortError') {
          setError('当前产品没有可用的预警回放，请更换产品或重新生成数据。');
        }
      });
    return () => controller.abort();
  }, [metadata, vegetableId]);

  const records = useMemo(() => (payload ? readRecords(payload) : []), [payload]);
  const cityMap = useMemo(
    () => new Map(payload?.cities.map((city) => [city.city_id, city]) ?? []),
    [payload],
  );
  const availableOrigins = useMemo(
    () =>
      records
        .filter((record) => record.cityId === cityId)
        .map((record) => record.originDate)
        .sort((a, b) => b.localeCompare(a)),
    [records, cityId],
  );
  const selectedRecord =
    records.find(
      (record) => record.cityId === cityId && record.originDate === originDate,
    ) ?? null;
  const currentCity = cityId ? cityMap.get(cityId) : null;
  const currentProduct = metadata?.products.find(
    (item) => item.vegetable_id === vegetableId,
  );
  const selectedOutcome = selectedRecord
    ? outcomePresentation[selectedRecord.outcomeType]
    : null;
  const cityTimeline = records
    .filter((record) => record.cityId === cityId)
    .sort((a, b) => a.originDate.localeCompare(b.originDate))
    .map((record) => ({
      ...record,
      eventPoint: record.eventLabel ? record.riskProbability : null,
    }));
  const originRecords = records
    .filter((record) => record.originDate === originDate)
    .sort((a, b) => b.riskProbability - a.riskProbability);
  const impactedCities = originRecords
    .filter((record) => record.eventLabel)
    .map((record) => cityMap.get(record.cityId)?.city_name_zh ?? record.cityId);

  let actionText = '选择一个历史预警起点查看建议。';
  if (selectedRecord?.predictedAlert) {
    actionText =
      '启动人工复核：核对供应商报价与库存，比较同品类其他城市，并在确认成本或供给变化后再交给 pricing engine。不要仅凭这条提醒自动调价。';
  } else if (selectedRecord?.outcomeType === 'false_negative') {
    actionText =
      '这是一次历史漏报。应检查当地行情与替代市场，但不能把事后信息加入当时的模型输入。';
  } else if (selectedRecord) {
    actionText =
      '冻结阈值没有触发提醒。保留常规监控；pricing engine 仍按成本、库存、利润和业务规则独立决策。';
  }

  return (
    <main className="min-h-screen bg-background text-foreground">
      <header className="border-b border-border/70 bg-card/86 backdrop-blur-xl">
        <div className="mx-auto flex w-full max-w-[1500px] flex-col gap-4 px-4 py-5 sm:px-6 lg:flex-row lg:items-center lg:justify-between lg:px-8">
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm">
              <Siren className="size-5" aria-hidden="true" />
            </div>
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-muted-foreground">
                Vegetable Price Intelligence
              </p>
              <h1 className="font-heading text-xl font-semibold tracking-tight sm:text-2xl">
                Price Risk Alert Replay
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
              href="/forecast"
              className="inline-flex h-8 items-center gap-1.5 rounded-md border border-primary/20 bg-primary/7 px-3 font-medium text-primary transition-colors hover:bg-primary/12"
            >
              <FlaskConical className="size-3.5" aria-hidden="true" />
              预测实验
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
              Historical replay
            </Badge>
            <span className="rounded-full border border-border bg-background/75 px-3 py-1.5 text-muted-foreground">
              数据截至 {metadata?.data_period.source_end ?? '2022-06-22'}
            </span>
          </div>
        </div>
      </header>

      <div className="mx-auto w-full max-w-[1500px] px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
        <section aria-labelledby="alert-controls" className="mb-5">
          <div className="mb-4 flex flex-col gap-2 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-[0.14em] text-primary">
                P3 · 价格风险预警
              </p>
              <h2 id="alert-controls" className="font-heading text-2xl font-semibold tracking-tight sm:text-3xl">
                回到当时，看模型会不会提前提醒
              </h2>
              <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">
                每个起点只使用当时可见信息，回放未来 14 天显著涨价事件。提醒只启动人工复核，不直接修改价格。
              </p>
            </div>
            {metadata && (
              <Badge className="w-fit bg-emerald-100 text-emerald-900 hover:bg-emerald-100">
                <ShieldCheck data-icon="inline-start" />
                {metadata.release_status === 'alert_release' ? '离线门槛通过' : '研究状态'}
              </Badge>
            )}
          </div>

          <Card className="border-0 bg-card/94 shadow-[0_12px_36px_rgb(43_66_54/6%)] ring-1 ring-foreground/8">
            <CardContent className="grid gap-3 pt-4 md:grid-cols-3">
              <div>
                <p className="mb-1.5 text-xs font-medium text-muted-foreground">产品</p>
                <Select
                  value={vegetableId?.toString() ?? ''}
                  onValueChange={(value) => setVegetableId(Number(value))}
                >
                  <SelectTrigger className="w-full"><SelectValue placeholder="选择产品" /></SelectTrigger>
                  <SelectContent>
                    {metadata?.products.map((product) => (
                      <SelectItem key={product.vegetable_id} value={product.vegetable_id.toString()}>
                        {product.vegetable_name_zh}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <p className="mb-1.5 text-xs font-medium text-muted-foreground">城市</p>
                <Select value={cityId ?? ''} onValueChange={setCityId} disabled={!payload}>
                  <SelectTrigger className="w-full"><SelectValue placeholder="选择城市" /></SelectTrigger>
                  <SelectContent>
                    {payload?.cities.map((city) => (
                      <SelectItem key={city.city_id} value={city.city_id}>
                        {city.city_name_zh} · {city.province_name_zh}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <p className="mb-1.5 text-xs font-medium text-muted-foreground">历史预警起点</p>
                <Select value={originDate ?? ''} onValueChange={setOriginDate} disabled={!payload}>
                  <SelectTrigger className="w-full"><SelectValue placeholder="选择预警日" /></SelectTrigger>
                  <SelectContent>
                    {availableOrigins.map((origin) => (
                      <SelectItem key={origin} value={origin}>{formatDate(origin)}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </CardContent>
          </Card>
        </section>

        {error ? (
          <Empty className="border border-border bg-card/90">
            <EmptyHeader>
              <EmptyMedia variant="icon"><CircleAlert /></EmptyMedia>
              <EmptyTitle>数据暂不可用</EmptyTitle>
              <EmptyDescription>{error}</EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : !metadata || !payload ? (
          <LoadingSurface />
        ) : (
          <section className="space-y-4" aria-live="polite">
            <Alert className="border-amber-300/70 bg-amber-50/80 text-amber-950">
              <CalendarDays className="size-4" />
              <AlertTitle>历史回放，不是今天的实时预警</AlertTitle>
              <AlertDescription>{metadata.boundary}</AlertDescription>
            </Alert>

            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <MetricCard
                label="当前风险概率"
                value={selectedRecord ? percentFormatter.format(selectedRecord.riskProbability) : '—'}
                detail={`冻结行动阈值 ${percentFormatter.format(metadata.action_threshold)}`}
                icon={<CircleGauge className="size-4" aria-hidden="true" />}
              />
              <MetricCard
                label="实际14日峰值涨幅"
                value={selectedRecord ? percentFormatter.format(selectedRecord.futurePeakReturn) : '—'}
                detail={selectedRecord ? `峰值日 ${formatDate(selectedRecord.futurePeakDate)}` : '等待选择'}
                icon={<Target className="size-4" aria-hidden="true" />}
              />
              <MetricCard
                label="历史结果"
                value={selectedOutcome?.label ?? '—'}
                detail={selectedOutcome?.detail ?? '等待选择'}
                icon={<CheckCircle2 className="size-4" aria-hidden="true" />}
              />
              <MetricCard
                label="事件提前量"
                value={selectedRecord?.eventLeadDays ? `${selectedRecord.eventLeadDays} 天` : '不适用'}
                detail={`最终测试平均 ${metadata.overall.mean_lead_days.toFixed(1)} 天`}
                icon={<TimerReset className="size-4" aria-hidden="true" />}
              />
            </div>

            <div className="grid gap-4 xl:grid-cols-[1.55fr_0.85fr]">
              <Card className="border-0 bg-card/94 ring-1 ring-foreground/8">
                <CardHeader className="grid-cols-[1fr_auto] items-start">
                  <div>
                    <CardTitle>{currentProduct?.vegetable_name_zh} · {currentCity?.city_name_zh} 风险轨迹</CardTitle>
                    <CardDescription>红点为实际事件；虚线是 validation 冻结行动阈值。</CardDescription>
                  </div>
                  {selectedOutcome && <Badge className={selectedOutcome.className}>{selectedOutcome.label}</Badge>}
                </CardHeader>
                <CardContent>
                  <ChartContainer config={riskChartConfig} className="h-[330px] w-full">
                    <LineChart data={cityTimeline} margin={{ left: 0, right: 14, top: 8, bottom: 0 }}>
                      <CartesianGrid vertical={false} />
                      <XAxis dataKey="originDate" tickFormatter={formatAxisDate} minTickGap={32} tickLine={false} axisLine={false} />
                      <YAxis domain={[0, 'auto']} tickFormatter={(value) => `${Math.round(Number(value) * 100)}%`} width={42} tickLine={false} axisLine={false} />
                      <ChartTooltip
                        content={<ChartTooltipContent labelFormatter={(value) => formatDate(String(value))} formatter={(value, name) => [`${(Number(value) * 100).toFixed(1)}%`, name === 'eventPoint' ? '实际事件风险点' : '模型风险概率']} />}
                      />
                      <ReferenceLine y={metadata.action_threshold} stroke="var(--chart-2)" strokeDasharray="5 5" />
                      <Line type="monotone" dataKey="riskProbability" stroke="var(--color-riskProbability)" strokeWidth={2} dot={false} />
                      <Line type="linear" dataKey="eventPoint" stroke="var(--color-eventPoint)" strokeWidth={0} connectNulls={false} dot={{ r: 4, fill: 'var(--destructive)', strokeWidth: 0 }} />
                    </LineChart>
                  </ChartContainer>
                </CardContent>
              </Card>

              <Card className="border-0 bg-primary text-primary-foreground shadow-[0_18px_54px_rgb(43_66_54/10%)]">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2"><BellRing className="size-5" /> 这条提醒怎么读</CardTitle>
                  <CardDescription className="text-primary-foreground/70">
                    {originDate ? formatDate(originDate) : '—'} · {currentCity?.city_name_zh}
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4 text-sm leading-6 text-primary-foreground/85">
                  <div>
                    <p className="font-semibold text-primary-foreground">发生了什么</p>
                    <p>{selectedRecord?.eventLabel ? `14 天内形成正式涨价事件，最高价 ¥${priceFormatter.format(selectedRecord.futurePeakPrice)}。` : '14 天内没有形成去重后的正式涨价事件。'}</p>
                  </div>
                  <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
                    <div>
                      <p className="font-semibold text-primary-foreground">严重程度</p>
                      <p>{selectedRecord ? severityLabels[selectedRecord.severity] : '—'}；事件门槛 {selectedRecord ? percentFormatter.format(selectedRecord.effectiveReturnThreshold) : '—'}。</p>
                    </div>
                    <div>
                      <p className="font-semibold text-primary-foreground">局部还是区域性</p>
                      <p>{selectedRecord ? scopeLabels[selectedRecord.eventScope] : '—'}；同产品当周原始触发占 {selectedRecord ? percentFormatter.format(selectedRecord.regionalRawEventShare) : '—'}。</p>
                    </div>
                  </div>
                  <div>
                    <p className="font-semibold text-primary-foreground">涉及哪些城市</p>
                    <p>{impactedCities.length ? `${impactedCities.slice(0, 6).join('、')}${impactedCities.length > 6 ? `等 ${impactedCities.length} 个城市` : ''}` : '该产品当周没有去重后的正式事件城市。'}</p>
                  </div>
                  <div className="rounded-lg bg-primary-foreground/10 p-3">
                    <p className="font-semibold text-primary-foreground">建议动作</p>
                    <p>{actionText}</p>
                  </div>
                </CardContent>
              </Card>
            </div>

            <div className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
              <Card className="border-0 bg-card/94 ring-1 ring-foreground/8">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2"><Gauge className="size-4 text-primary" /> 最终测试 PR 曲线</CardTitle>
                  <CardDescription>比较不同阈值下查得更多事件与减少误报的取舍。</CardDescription>
                </CardHeader>
                <CardContent>
                  <ChartContainer config={prChartConfig} className="h-[280px] w-full">
                    <LineChart data={metadata.pr_curve} margin={{ left: 0, right: 10, top: 8, bottom: 0 }}>
                      <CartesianGrid vertical={false} />
                      <XAxis type="number" dataKey="recall" domain={[0, 1]} tickFormatter={(value) => `${Math.round(Number(value) * 100)}%`} tickLine={false} axisLine={false} />
                      <YAxis domain={[0, 1]} tickFormatter={(value) => `${Math.round(Number(value) * 100)}%`} width={42} tickLine={false} axisLine={false} />
                      <ChartTooltip content={<ChartTooltipContent formatter={(value, name) => [`${(Number(value) * 100).toFixed(1)}%`, name === 'precision' ? 'Precision' : String(name)]} />} />
                      <ReferenceLine y={metadata.overall.prevalence} stroke="var(--chart-2)" strokeDasharray="5 5" />
                      <Line type="monotone" dataKey="precision" stroke="var(--color-precision)" strokeWidth={2} dot={false} />
                    </LineChart>
                  </ChartContainer>
                </CardContent>
              </Card>

              <Card className="border-0 bg-card/94 ring-1 ring-foreground/8">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2"><CircleAlert className="size-4 text-primary" /> 它能做什么，不能做什么</CardTitle>
                  <CardDescription>通过离线门槛不等于可以无人值守。</CardDescription>
                </CardHeader>
                <CardContent className="grid gap-4 text-sm leading-6 sm:grid-cols-2">
                  <div className="rounded-lg bg-emerald-50 p-4 text-emerald-950">
                    <p className="font-semibold">适合</p>
                    <p className="mt-1">提前安排供应与库存复核、筛选需要人工关注的产品—城市、比较本地和跨城风险。</p>
                  </div>
                  <div className="rounded-lg bg-rose-50 p-4 text-rose-950">
                    <p className="font-semibold">不适合</p>
                    <p className="mt-1">自动提价、替代成本与利润模型、声称实时行情，或把风险概率当作确定会涨。</p>
                  </div>
                  <div className="sm:col-span-2">
                    <p className="font-medium">最终测试证据</p>
                    <p className="text-muted-foreground">
                      PR-AUC {metadata.overall.average_precision.toFixed(3)}，比简单基线高 {percentFormatter.format(metadata.overall.average_precision_lift_vs_baseline)}；召回 {percentFormatter.format(metadata.overall.recall)}，precision {percentFormatter.format(metadata.overall.precision)}。发出的提醒中仍有 {percentFormatter.format(metadata.overall.false_alert_share)} 是误报，必须人工复核。
                    </p>
                  </div>
                </CardContent>
              </Card>
            </div>

            <Card className="border-0 bg-card/94 ring-1 ring-foreground/8">
              <CardHeader>
                <CardTitle className="flex items-center gap-2"><MapPinned className="size-4 text-primary" /> 同产品、同预警日起点的城市风险</CardTitle>
                <CardDescription>按风险概率排序，最多展示前 12 个城市；结果列是事后历史验证。</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="overflow-x-auto rounded-lg border border-border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>城市</TableHead>
                        <TableHead className="text-right">风险概率</TableHead>
                        <TableHead className="text-right">14日峰值涨幅</TableHead>
                        <TableHead>提醒</TableHead>
                        <TableHead>历史结果</TableHead>
                        <TableHead>范围</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {originRecords.slice(0, 12).map((record) => {
                        const city = cityMap.get(record.cityId);
                        const outcome = outcomePresentation[record.outcomeType];
                        return (
                          <TableRow key={record.cityId} className={record.cityId === cityId ? 'bg-primary/5' : ''}>
                            <TableCell className="font-medium">{city?.city_name_zh ?? record.cityId}</TableCell>
                            <TableCell className="text-right tabular-nums">{percentFormatter.format(record.riskProbability)}</TableCell>
                            <TableCell className="text-right tabular-nums">{percentFormatter.format(record.futurePeakReturn)}</TableCell>
                            <TableCell>{record.predictedAlert ? '触发复核' : '未触发'}</TableCell>
                            <TableCell><Badge className={outcome.className}>{outcome.label}</Badge></TableCell>
                            <TableCell>{scopeLabels[record.eventScope]}</TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                </div>
              </CardContent>
            </Card>

            <Card className="border-0 bg-muted/75 ring-1 ring-foreground/7">
              <CardContent className="grid gap-4 pt-4 text-sm leading-6 md:grid-cols-3">
                <div>
                  <p className="font-semibold">事件口径</p>
                  <p className="text-muted-foreground">{metadata.event_definition}</p>
                </div>
                <div>
                  <p className="font-semibold">数据质量</p>
                  <p className="text-muted-foreground">当前起点为 {selectedRecord?.originQuality ?? '—'}，价格填充 {selectedRecord?.originFillDays ?? 0} 天；poor 目标已排除。</p>
                </div>
                <div>
                  <p className="font-semibold">与 pricing engine 的关系</p>
                  <p className="text-muted-foreground">预警层决定“是否值得复核”；pricing engine 再结合成本、库存、利润与规则决定“价格怎么定”。</p>
                </div>
              </CardContent>
            </Card>
          </section>
        )}
      </div>
    </main>
  );
}
