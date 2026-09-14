'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  ReferenceLine,
  XAxis,
  YAxis,
} from 'recharts';
import {
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  CalendarDays,
  BriefcaseBusiness,
  CircleAlert,
  Database,
  CircleGauge,
  FileWarning,
  Info,
  Leaf,
  MapPin,
  Minus,
  ShieldCheck,
  Siren,
  FlaskConical,
  TrendingUp,
  Truck,
} from 'lucide-react';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from '@/components/ui/chart';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from '@/components/ui/empty';
import { Progress, ProgressLabel, ProgressValue } from '@/components/ui/progress';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

type MetadataProduct = {
  vegetable_id: number;
  vegetable_code: string;
  vegetable_name_zh: string;
  edible_part_group: string;
  perishability_group: string;
  storability_group: string;
  typical_price_level: string;
  data_file: string;
  monthly_record_count: number;
  observed_city_count: number;
  first_month: string;
  last_month: string;
  monitor_eligible_city_count: number;
  tier_counts: { A: number; B: number; C: number };
};

type MetadataCity = {
  city_id: string;
  city_name_zh: string;
  province_name_zh: string;
  included_market_count: number;
};

type Metadata = {
  title: string;
  historical_only: boolean;
  data_period: {
    start: string;
    end: string;
    last_complete_month: string;
    granularity: string;
    price_unit: string;
  };
  ranking_policy: {
    eligible_tiers: string[];
    minimum_valid_days_in_month: number;
  };
  defaults: {
    vegetable_id: number;
    city_id: string;
    month: string;
  };
  cities: MetadataCity[];
  products: MetadataProduct[];
};

type ProductPayload = {
  product: MetadataProduct;
  data_period: Metadata['data_period'];
  city_profile_fields: string[];
  city_profiles: Array<Array<string | number | boolean | null>>;
  record_fields: string[];
  records: Array<Array<string | number>>;
};

type CityProfile = {
  cityId: string;
  tier: string;
  monitorEligible: boolean;
  coverageRate: number;
  totalValidDays: number;
  reliability: number | null;
  tierReason: string;
};

type MonthRecord = {
  cityId: string;
  month: string;
  median: number;
  p25: number;
  p75: number;
  validDays: number;
  firstDate: string;
  lastDate: string;
  reliability: number;
  goodDays: number;
  cautionDays: number;
  poorDays: number;
  medianMarkets: number;
  maxMarkets: number;
  sourceRecords: number;
};

const chartConfig = {
  median: { label: '月度中位价格', color: 'var(--chart-1)' },
  p25: { label: '25 分位', color: 'var(--card)' },
  p75: { label: '75 分位', color: 'var(--chart-2)' },
} satisfies ChartConfig;

const priceFormatter = new Intl.NumberFormat('zh-CN', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const integerFormatter = new Intl.NumberFormat('zh-CN');

function formatMonth(month: string) {
  const [year, monthNumber] = month.split('-');
  return `${year}年${Number(monthNumber)}月`;
}

function formatAxisMonth(month: string) {
  const [year, monthNumber] = month.split('-');
  return monthNumber === '01' ? year : `${Number(monthNumber)}月`;
}

function quantile(values: number[], probability: number) {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const position = (sorted.length - 1) * probability;
  const lowerIndex = Math.floor(position);
  const upperIndex = Math.ceil(position);
  if (lowerIndex === upperIndex) return sorted[lowerIndex];
  const weight = position - lowerIndex;
  return sorted[lowerIndex] * (1 - weight) + sorted[upperIndex] * weight;
}

function daysInMonth(month: string) {
  const [year, monthNumber] = month.split('-').map(Number);
  return new Date(year, monthNumber, 0).getDate();
}

function readRecords(payload: ProductPayload): MonthRecord[] {
  return payload.records.map((record) => ({
    cityId: String(record[0]),
    month: String(record[1]),
    median: Number(record[2]),
    p25: Number(record[3]),
    p75: Number(record[4]),
    validDays: Number(record[5]),
    firstDate: String(record[6]),
    lastDate: String(record[7]),
    reliability: Number(record[8]),
    goodDays: Number(record[9]),
    cautionDays: Number(record[10]),
    poorDays: Number(record[11]),
    medianMarkets: Number(record[12]),
    maxMarkets: Number(record[13]),
    sourceRecords: Number(record[14]),
  }));
}

function readProfiles(payload: ProductPayload): CityProfile[] {
  return payload.city_profiles.map((profile) => ({
    cityId: String(profile[0]),
    tier: String(profile[1]),
    monitorEligible: Boolean(profile[2]),
    coverageRate: Number(profile[3]),
    totalValidDays: Number(profile[4]),
    reliability: profile[5] === null ? null : Number(profile[5]),
    tierReason: String(profile[6]),
  }));
}

function MetricCard({
  label,
  value,
  detail,
  icon,
  tone = 'neutral',
}: {
  label: string;
  value: string;
  detail: string;
  icon: React.ReactNode;
  tone?: 'neutral' | 'positive' | 'negative';
}) {
  const toneClass =
    tone === 'positive'
      ? 'text-emerald-700'
      : tone === 'negative'
        ? 'text-rose-700'
        : 'text-foreground';
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
        <div className={`font-heading text-2xl font-semibold tabular-nums ${toneClass}`}>
          {value}
        </div>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">{detail}</p>
      </CardContent>
    </Card>
  );
}

function LoadingSurface() {
  return (
    <>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {[0, 1, 2, 3].map((item) => (
          <Card key={item} className="border-0 bg-card/90">
            <CardContent className="space-y-3 pt-2">
              <Skeleton className="h-3 w-24" />
              <Skeleton className="h-8 w-32" />
              <Skeleton className="h-3 w-40" />
            </CardContent>
          </Card>
        ))}
      </div>
      <Card className="mt-4 border-0 bg-card/90">
        <CardHeader>
          <Skeleton className="h-5 w-48" />
          <Skeleton className="h-3 w-64" />
        </CardHeader>
        <CardContent>
          <Skeleton className="h-[360px] w-full" />
        </CardContent>
      </Card>
    </>
  );
}

export default function Home() {
  const [metadata, setMetadata] = useState<Metadata | null>(null);
  const [payload, setPayload] = useState<ProductPayload | null>(null);
  const [vegetableId, setVegetableId] = useState<number | null>(null);
  const [cityId, setCityId] = useState<string | null>(null);
  const cityIdRef = useRef<string | null>(null);
  const [selectedMonth, setSelectedMonth] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetch('/data/metadata.json', { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error('metadata');
        return response.json() as Promise<Metadata>;
      })
      .then((data) => {
        setMetadata(data);
        setVegetableId(data.defaults.vegetable_id);
        cityIdRef.current = data.defaults.city_id;
        setCityId(data.defaults.city_id);
        setSelectedMonth(data.defaults.month);
      })
      .catch((fetchError: Error) => {
        if (fetchError.name !== 'AbortError') {
          setError('历史数据目录未能载入，请确认站点数据已生成后再刷新。');
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
        const profiles = readProfiles(data);
        const currentProfile = profiles.find((item) => item.cityId === cityIdRef.current);
        const fallbackProfile =
          profiles.find((item) => item.cityId === metadata.defaults.city_id && item.monitorEligible) ??
          profiles.find((item) => item.monitorEligible);
        const nextCity = currentProfile?.monitorEligible ? currentProfile.cityId : fallbackProfile?.cityId;
        if (!nextCity) throw new Error('eligible-city');
        const productRecords = readRecords(data).filter((record) => record.cityId === nextCity);
        const completeMonths = productRecords
          .map((record) => record.month)
          .filter((month) => month <= metadata.data_period.last_complete_month);
        const nextMonth = completeMonths.includes(metadata.defaults.month)
          ? metadata.defaults.month
          : completeMonths.at(-1);
        cityIdRef.current = nextCity;
        setCityId(nextCity);
        setSelectedMonth(nextMonth ?? null);
        setPayload(data);
      })
      .catch((fetchError: Error) => {
        if (fetchError.name !== 'AbortError') {
          setError('当前蔬菜的数据文件未能载入，请更换选项或稍后刷新。');
        }
      });
    return () => controller.abort();
  }, [metadata, vegetableId]);

  const records = useMemo(() => (payload ? readRecords(payload) : []), [payload]);
  const profiles = useMemo(() => (payload ? readProfiles(payload) : []), [payload]);
  const profileMap = useMemo(
    () => new Map(profiles.map((profile) => [profile.cityId, profile])),
    [profiles],
  );
  const cityMap = useMemo(
    () => new Map(metadata?.cities.map((city) => [city.city_id, city]) ?? []),
    [metadata],
  );
  const eligibleCities = useMemo(() => {
    if (!metadata) return [];
    return profiles
      .filter((profile) => profile.monitorEligible)
      .map((profile) => metadata.cities.find((city) => city.city_id === profile.cityId))
      .filter((city): city is MetadataCity => Boolean(city))
      .sort((a, b) =>
        `${a.province_name_zh}${a.city_name_zh}`.localeCompare(
          `${b.province_name_zh}${b.city_name_zh}`,
          'zh-CN',
        ),
      );
  }, [metadata, profiles]);

  const cityRecords = useMemo(() => {
    if (!metadata || !cityId) return [];
    return records.filter(
      (record) =>
        record.cityId === cityId && record.month <= metadata.data_period.last_complete_month,
    );
  }, [cityId, metadata, records]);

  const months = cityRecords.map((record) => record.month);
  const selectedRecord = cityRecords.find((record) => record.month === selectedMonth) ?? null;
  const selectedIndex = selectedRecord
    ? cityRecords.findIndex((record) => record.month === selectedRecord.month)
    : -1;
  const previousRecord = selectedIndex > 0 ? cityRecords[selectedIndex - 1] : null;
  const monthChange =
    selectedRecord && previousRecord
      ? ((selectedRecord.median / previousRecord.median - 1) * 100)
      : null;

  const ranking = useMemo(() => {
    if (!metadata || !selectedMonth) return [];
    const allowedTiers = new Set(metadata.ranking_policy.eligible_tiers);
    return records
      .filter((record) => {
        const profile = profileMap.get(record.cityId);
        return (
          record.month === selectedMonth &&
          record.validDays >= metadata.ranking_policy.minimum_valid_days_in_month &&
          profile !== undefined &&
          allowedTiers.has(profile.tier)
        );
      })
      .sort((a, b) => b.median - a.median);
  }, [metadata, profileMap, records, selectedMonth]);

  const rankIndex = cityId ? ranking.findIndex((record) => record.cityId === cityId) : -1;
  const currentCity = cityId ? cityMap.get(cityId) : null;
  const currentProfile = cityId ? profileMap.get(cityId) : null;
  const currentProduct = metadata?.products.find((item) => item.vegetable_id === vegetableId);
  const chartData = cityRecords.map((record) => ({
    ...record,
    selected: record.month === selectedMonth,
  }));
  const goodShare = selectedRecord
    ? selectedRecord.goodDays / Math.max(1, selectedRecord.validDays)
    : null;
  const rankingPrices = ranking.map((record) => record.median);
  const cityPriceMedian = quantile(rankingPrices, 0.5);
  const cityPriceP25 = quantile(rankingPrices, 0.25);
  const cityPriceP75 = quantile(rankingPrices, 0.75);
  const priceSpread =
    ranking.length > 1 && ranking.at(-1)?.median
      ? ((ranking[0].median / (ranking.at(-1)?.median ?? ranking[0].median) - 1) * 100)
      : null;

  const provinceSummary = useMemo(() => {
    const grouped = new Map<string, number[]>();
    ranking.forEach((record) => {
      const province = cityMap.get(record.cityId)?.province_name_zh;
      if (!province) return;
      grouped.set(province, [...(grouped.get(province) ?? []), record.median]);
    });
    return [...grouped.entries()]
      .map(([province, values]) => ({
        province,
        cityCount: values.length,
        median: quantile(values, 0.5),
      }))
      .filter((item) => item.cityCount >= 2)
      .sort((a, b) => b.median - a.median);
  }, [cityMap, ranking]);

  const seasonalData = useMemo(() => {
    const grouped = new Map<number, number[]>();
    cityRecords.forEach((record) => {
      const monthNumber = Number(record.month.slice(5, 7));
      grouped.set(monthNumber, [...(grouped.get(monthNumber) ?? []), record.median]);
    });
    return Array.from({ length: 12 }, (_, index) => index + 1)
      .map((monthNumber) => {
        const values = grouped.get(monthNumber) ?? [];
        if (!values.length) return null;
        return {
          month: `${monthNumber}月`,
          monthNumber,
          median: quantile(values, 0.5),
          p25: quantile(values, 0.25),
          p75: quantile(values, 0.75),
          sampleYears: values.length,
        };
      })
      .filter((item): item is NonNullable<typeof item> => item !== null);
  }, [cityRecords]);
  const seasonalHigh = [...seasonalData].sort((a, b) => b.median - a.median)[0];
  const seasonalLow = [...seasonalData].sort((a, b) => a.median - b.median)[0];
  const selectedCalendarMonth = selectedMonth ? `${Number(selectedMonth.slice(5, 7))}月` : null;
  const selectedMonthCoverage = selectedRecord
    ? selectedRecord.validDays / daysInMonth(selectedRecord.month)
    : 0;

  function handleCityChange(nextCityId: string) {
    cityIdRef.current = nextCityId;
    setCityId(nextCityId);
    const nextCityRecords = records.filter(
      (record) =>
        record.cityId === nextCityId &&
        (!metadata || record.month <= metadata.data_period.last_complete_month),
    );
    const availableMonths = nextCityRecords.map((record) => record.month);
    setSelectedMonth((current) =>
      current && availableMonths.includes(current) ? current : (availableMonths.at(-1) ?? null),
    );
  }

  function handleVegetableChange(nextVegetableId: number) {
    setPayload(null);
    setError(null);
    setVegetableId(nextVegetableId);
  }

  return (
    <main className="min-h-screen bg-background text-foreground">
      <header className="border-b border-border/70 bg-card/86 backdrop-blur-xl">
        <div className="mx-auto flex w-full max-w-[1500px] flex-col gap-4 px-4 py-5 sm:px-6 lg:flex-row lg:items-center lg:justify-between lg:px-8">
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm">
              <Leaf className="size-5" aria-hidden="true" />
            </div>
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-muted-foreground">
                Vegetable Price Intelligence
              </p>
              <h1 className="font-heading text-xl font-semibold tracking-tight sm:text-2xl">
                Historical Price Monitor
              </h1>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <Link
              href="/case-study"
              className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-background/75 px-3 font-medium transition-colors hover:bg-muted"
            >
              <BriefcaseBusiness className="size-3.5" aria-hidden="true" />
              Case Study
            </Link>
            <Link
              href="/alerts"
              className="inline-flex h-8 items-center gap-1.5 rounded-md border border-primary/20 bg-primary/7 px-3 font-medium text-primary transition-colors hover:bg-primary/12"
            >
              <Siren className="size-3.5" aria-hidden="true" />
              风险预警
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
            <Link
              href="/propagation"
              className="inline-flex h-8 items-center gap-1.5 rounded-md border border-primary/20 bg-primary/7 px-3 font-medium text-primary transition-colors hover:bg-primary/12"
            >
              <CircleGauge className="size-3.5" aria-hidden="true" />
              共同冲击
            </Link>
            <Badge className="bg-amber-100 text-amber-900 hover:bg-amber-100">
              <Database data-icon="inline-start" />
              Historical only
            </Badge>
            <span className="flex items-center gap-1.5 rounded-full border border-border bg-background/75 px-3 py-1.5 text-muted-foreground">
              <CalendarDays className="size-3.5" aria-hidden="true" />
              数据截至 {metadata?.data_period.end ?? '2022-06-22'}
            </span>
          </div>
        </div>
      </header>

      <div className="mx-auto w-full max-w-[1500px] px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
        <section aria-labelledby="monitor-controls" className="mb-5">
          <div className="mb-4 flex flex-col gap-2 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-[0.14em] text-primary">
                Market-to-Pricing intelligence · 2014–2022
              </p>
              <h2 id="monitor-controls" className="font-heading text-2xl font-semibold tracking-tight">
                从城市价格差异到 Pricing 决策输入
              </h2>
              <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">
                先比较城市价格离散与季节位置，再沿着预测、预警和采购情景，把市场信号转化为成本与毛利复核所需的上游证据。
              </p>
            </div>
            {currentProduct && (
              <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                <span className="rounded-md bg-muted px-2.5 py-1.5">
                  {currentProduct.perishability_group === 'high' ? '高易腐' : '耐储型'}
                </span>
                <span className="rounded-md bg-muted px-2.5 py-1.5">
                  可比较城市 {currentProduct.monitor_eligible_city_count}
                </span>
              </div>
            )}
          </div>

          <div className="mb-4 rounded-xl border border-primary/15 bg-card/82 p-3 shadow-sm" aria-label="Market-to-Pricing 决策链">
            <div className="grid grid-cols-2 gap-2 lg:grid-cols-[1fr_auto_1fr_auto_1fr_auto_1fr_auto_1fr_auto_1.15fr] lg:items-stretch">
              <div className="rounded-lg bg-muted/65 px-3 py-2">
                <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-primary">01 · 市场基准</p>
                <p className="mt-0.5 text-xs font-medium">价格离散与季节位置</p>
              </div>
              <ArrowRight className="hidden size-4 self-center text-muted-foreground lg:block" aria-hidden="true" />
              <div className="rounded-lg bg-muted/65 px-3 py-2">
                <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-primary">02 · 价格预期</p>
                <p className="mt-0.5 text-xs font-medium">模型、区间与基线回退</p>
              </div>
              <ArrowRight className="hidden size-4 self-center text-muted-foreground lg:block" aria-hidden="true" />
              <div className="rounded-lg bg-muted/65 px-3 py-2">
                <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-primary">03 · 风险信号</p>
                <p className="mt-0.5 text-xs font-medium">涨价事件与人工复核</p>
              </div>
              <ArrowRight className="hidden size-4 self-center text-muted-foreground lg:block" aria-hidden="true" />
              <div className="rounded-lg bg-muted/65 px-3 py-2">
                <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-primary">04 · 采购情景</p>
                <p className="mt-0.5 text-xs font-medium">空间摩擦与到岸成本</p>
              </div>
              <ArrowRight className="hidden size-4 self-center text-muted-foreground lg:block" aria-hidden="true" />
              <div className="rounded-lg bg-muted/65 px-3 py-2">
                <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-primary">05 · 冲击暴露</p>
                <p className="mt-0.5 text-xs font-medium">共同压力与复核范围</p>
              </div>
              <ArrowRight className="hidden size-4 self-center text-muted-foreground lg:block" aria-hidden="true" />
              <div className="col-span-2 rounded-lg bg-primary px-3 py-2 text-primary-foreground lg:col-span-1">
                <p className="text-[10px] font-semibold uppercase tracking-[0.14em] opacity-75">06 · Pricing Engine</p>
                <p className="mt-0.5 text-xs font-medium">成本基准与毛利复核输入</p>
              </div>
            </div>
            <p className="mt-2 text-xs leading-5 text-muted-foreground">
              本项目提供市场、风险与成本情报；pricing engine 再结合库存、客户、利润和审批规则形成可执行报价。
            </p>
          </div>

          <Card className="border-0 bg-[linear-gradient(115deg,var(--card),color-mix(in_oklab,var(--accent)_55%,var(--card)))] py-3 shadow-[0_14px_44px_rgb(43_66_54/7%)] ring-1 ring-foreground/8">
            <CardContent className="grid gap-3 px-3 sm:grid-cols-2 sm:px-4 lg:grid-cols-[1.1fr_1.2fr_0.9fr_auto] lg:items-end">
              <div className="grid gap-1.5 text-xs font-medium text-muted-foreground">
                <p id="vegetable-selector-label">蔬菜品类</p>
                <Select
                  value={vegetableId === null ? null : String(vegetableId)}
                  onValueChange={(value) => value && handleVegetableChange(Number(value))}
                >
                  <SelectTrigger aria-labelledby="vegetable-selector-label" className="h-10! w-full bg-card px-3 text-foreground shadow-xs">
                    <SelectValue>
                      {currentProduct
                        ? `${currentProduct.vegetable_name_zh} · ${currentProduct.vegetable_code}`
                        : '载入品类'}
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
                <p id="city-selector-label">城市与覆盖等级</p>
                <Select
                  value={cityId}
                  onValueChange={(value) => value && handleCityChange(String(value))}
                  disabled={!payload}
                >
                  <SelectTrigger aria-labelledby="city-selector-label" className="h-10! w-full bg-card px-3 text-foreground shadow-xs">
                    <SelectValue>
                      {currentCity && currentProfile
                        ? `${currentCity.city_name_zh} · ${currentCity.province_name_zh} · Tier ${currentProfile.tier}`
                        : '载入城市'}
                    </SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {eligibleCities.map((city) => (
                      <SelectItem key={city.city_id} value={city.city_id}>
                        {city.city_name_zh} · {city.province_name_zh} · Tier{' '}
                        {profileMap.get(city.city_id)?.tier}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="grid gap-1.5 text-xs font-medium text-muted-foreground">
                <p id="month-selector-label">历史月份</p>
                <Select
                  value={selectedMonth}
                  onValueChange={(value) => value && setSelectedMonth(String(value))}
                  disabled={!payload}
                >
                  <SelectTrigger aria-labelledby="month-selector-label" className="h-10! w-full bg-card px-3 text-foreground shadow-xs">
                    <SelectValue>{selectedMonth ? formatMonth(selectedMonth) : '载入月份'}</SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {[...months].reverse().map((month) => (
                      <SelectItem key={month} value={month}>
                        {formatMonth(month)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="flex h-10 items-center gap-2 rounded-lg border border-primary/15 bg-primary/7 px-3 text-xs text-primary sm:col-span-2 lg:col-span-1">
                <ShieldCheck className="size-4 shrink-0" aria-hidden="true" />
                <span className="font-medium">仅 Tier A/B 进入默认比较</span>
              </div>
            </CardContent>
          </Card>
        </section>

        {error ? (
          <Alert variant="destructive" className="bg-card py-4">
            <CircleAlert />
            <AlertTitle>数据暂时不可用</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : !metadata || !payload ? (
          <LoadingSurface />
        ) : !selectedRecord ? (
          <Empty className="min-h-[360px] border border-border bg-card/90">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <FileWarning />
              </EmptyMedia>
              <EmptyTitle>这个组合没有可比较的月度记录</EmptyTitle>
              <EmptyDescription>
                请更换城市或月份。Tier A/B 只代表全期覆盖合格，并不保证每个月都有足够观测。
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <section aria-live="polite" aria-busy="false">
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <MetricCard
                label="月度中位价格"
                value={`¥${priceFormatter.format(selectedRecord.median)}/kg`}
                detail={`${formatMonth(selectedRecord.month)} · ${selectedRecord.validDays} 个有效日`}
                icon={<TrendingUp className="size-4" aria-hidden="true" />}
              />
              <MetricCard
                label="较前一有效月"
                value={monthChange === null ? '—' : `${monthChange >= 0 ? '+' : ''}${monthChange.toFixed(1)}%`}
                detail={previousRecord ? `对比 ${formatMonth(previousRecord.month)}` : '没有可比的前期记录'}
                tone={monthChange === null ? 'neutral' : monthChange > 0 ? 'negative' : 'positive'}
                icon={
                  monthChange === null || Math.abs(monthChange) < 0.05 ? (
                    <Minus className="size-4" aria-hidden="true" />
                  ) : monthChange > 0 ? (
                    <ArrowUpRight className="size-4" aria-hidden="true" />
                  ) : (
                    <ArrowDownRight className="size-4" aria-hidden="true" />
                  )
                }
              />
              <MetricCard
                label="同期高价排名"
                value={rankIndex >= 0 ? `#${rankIndex + 1} / ${ranking.length}` : '不可比较'}
                detail={`同品类、同月份；至少 ${metadata.ranking_policy.minimum_valid_days_in_month} 个有效日`}
                icon={<MapPin className="size-4" aria-hidden="true" />}
              />
              <MetricCard
                label="来源可靠性"
                value={`${Math.round(selectedRecord.reliability * 100)} / 100`}
                detail={`Tier ${currentProfile?.tier ?? '—'} · ${Math.round((goodShare ?? 0) * 100)}% 观测日为 good`}
                icon={<ShieldCheck className="size-4" aria-hidden="true" />}
              />
            </div>

            <Card className="mt-4 border-0 bg-card/94 shadow-[0_18px_54px_rgb(43_66_54/7%)] ring-1 ring-foreground/8">
              <CardHeader className="border-b border-border/65 pb-4">
                <CardTitle className="text-lg">
                  {currentProduct?.vegetable_name_zh} · {currentCity?.city_name_zh} 历史价格
                </CardTitle>
                <CardDescription>
                  实线为月度中位价格，浅色区间为月内 25–75 分位；单位为人民币/公斤。
                </CardDescription>
                <CardAction className="flex items-center gap-2">
                  <Badge variant="outline" className="bg-background/70">
                    {chartData.length} 个月
                  </Badge>
                  <Badge variant="secondary">Tier {currentProfile?.tier}</Badge>
                </CardAction>
              </CardHeader>
              <CardContent className="pt-4">
                <ChartContainer
                  config={chartConfig}
                  className="h-[370px] w-full aspect-auto sm:h-[410px]"
                >
                  <AreaChart data={chartData} margin={{ left: 0, right: 12, top: 12, bottom: 0 }}>
                    <CartesianGrid vertical={false} strokeDasharray="3 5" />
                    <XAxis
                      dataKey="month"
                      axisLine={false}
                      tickLine={false}
                      minTickGap={36}
                      tickFormatter={formatAxisMonth}
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
                      cursor={{ stroke: 'var(--border)', strokeDasharray: '3 3' }}
                      content={
                        <ChartTooltipContent
                          labelFormatter={(_, payloadItems) => {
                            const month = payloadItems?.[0]?.payload?.month;
                            return month ? formatMonth(String(month)) : '';
                          }}
                        />
                      }
                    />
                    <Area
                      type="monotone"
                      dataKey="p75"
                      stroke="transparent"
                      fill="var(--color-p75)"
                      fillOpacity={0.17}
                      isAnimationActive={false}
                    />
                    <Area
                      type="monotone"
                      dataKey="p25"
                      stroke="transparent"
                      fill="var(--card)"
                      fillOpacity={1}
                      isAnimationActive={false}
                    />
                    <Line
                      type="monotone"
                      dataKey="median"
                      stroke="var(--color-median)"
                      strokeWidth={2.4}
                      dot={false}
                      activeDot={{ r: 4, strokeWidth: 2, fill: 'var(--card)' }}
                      isAnimationActive={false}
                    />
                    {selectedMonth && (
                      <ReferenceLine
                        x={selectedMonth}
                        stroke="var(--chart-3)"
                        strokeDasharray="4 4"
                        strokeWidth={1.5}
                      />
                    )}
                  </AreaChart>
                </ChartContainer>
                <div className="mt-3 grid gap-2 border-t border-border/65 pt-3 text-xs text-muted-foreground sm:grid-cols-3">
                  <span>
                    月内区间：¥{priceFormatter.format(selectedRecord.p25)}–¥
                    {priceFormatter.format(selectedRecord.p75)}
                  </span>
                  <span>报告市场中位数：{selectedRecord.medianMarkets.toFixed(1)}</span>
                  <span>来源记录：{integerFormatter.format(selectedRecord.sourceRecords)} 条</span>
                </div>
              </CardContent>
            </Card>

            <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1.08fr)_minmax(0,0.92fr)]">
              <Card className="border-0 bg-card/94 shadow-[0_14px_44px_rgb(43_66_54/6%)] ring-1 ring-foreground/8">
                <CardHeader className="border-b border-border/65 pb-4">
                  <CardTitle>同期城市价格梯度</CardTitle>
                  <CardDescription>
                    {formatMonth(selectedMonth ?? metadata.defaults.month)} · Tier A/B 且至少{' '}
                    {metadata.ranking_policy.minimum_valid_days_in_month} 个有效日，点击城市可切换主视图。
                  </CardDescription>
                  <CardAction>
                    <Badge variant="outline" className="bg-background/70">
                      {priceSpread === null ? '样本不足' : `高低价差 ${priceSpread.toFixed(0)}%`}
                    </Badge>
                  </CardAction>
                </CardHeader>
                <CardContent className="pt-4">
                  <div className="mb-3 grid gap-2 sm:grid-cols-3">
                    <div className="rounded-lg bg-muted/75 p-3">
                      <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                        最高城市
                      </p>
                      <p className="mt-1 font-medium">
                        {ranking[0] ? cityMap.get(ranking[0].cityId)?.city_name_zh : '—'}
                      </p>
                      <p className="mt-0.5 text-xs tabular-nums text-muted-foreground">
                        {ranking[0] ? `¥${priceFormatter.format(ranking[0].median)}/kg` : '无可比数据'}
                      </p>
                    </div>
                    <div className="rounded-lg bg-muted/75 p-3">
                      <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                        城市中位
                      </p>
                      <p className="mt-1 font-medium tabular-nums">
                        {ranking.length ? `¥${priceFormatter.format(cityPriceMedian)}/kg` : '—'}
                      </p>
                      <p className="mt-0.5 text-xs text-muted-foreground">
                        IQR ¥{priceFormatter.format(cityPriceP25)}–¥{priceFormatter.format(cityPriceP75)}
                      </p>
                    </div>
                    <div className="rounded-lg bg-muted/75 p-3">
                      <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                        最低城市
                      </p>
                      <p className="mt-1 font-medium">
                        {ranking.at(-1) ? cityMap.get(ranking.at(-1)!.cityId)?.city_name_zh : '—'}
                      </p>
                      <p className="mt-0.5 text-xs tabular-nums text-muted-foreground">
                        {ranking.at(-1)
                          ? `¥${priceFormatter.format(ranking.at(-1)!.median)}/kg`
                          : '无可比数据'}
                      </p>
                    </div>
                  </div>

                  <div className="max-h-[420px] overflow-y-auto rounded-lg border border-border/70">
                    <Table>
                      <TableHeader className="sticky top-0 z-10 bg-card">
                        <TableRow>
                          <TableHead className="w-14">排名</TableHead>
                          <TableHead>城市</TableHead>
                          <TableHead className="hidden sm:table-cell">省份</TableHead>
                          <TableHead className="hidden text-right md:table-cell">可靠性</TableHead>
                          <TableHead className="text-right">价格</TableHead>
                          <TableHead className="w-16 text-right">Tier</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {ranking.map((record, index) => {
                          const city = cityMap.get(record.cityId);
                          const profile = profileMap.get(record.cityId);
                          return (
                            <TableRow
                              key={record.cityId}
                              data-state={record.cityId === cityId ? 'selected' : undefined}
                            >
                              <TableCell className="font-mono text-xs text-muted-foreground">
                                {String(index + 1).padStart(2, '0')}
                              </TableCell>
                              <TableCell>
                                <button
                                  type="button"
                                  className="font-medium text-foreground underline-offset-4 hover:text-primary hover:underline focus-visible:rounded-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
                                  onClick={() => handleCityChange(record.cityId)}
                                  aria-label={`切换到${city?.city_name_zh ?? record.cityId}`}
                                >
                                  {city?.city_name_zh ?? record.cityId}
                                </button>
                                <span className="ml-2 text-[10px] text-muted-foreground sm:hidden">
                                  {city?.province_name_zh}
                                </span>
                              </TableCell>
                              <TableCell className="hidden text-muted-foreground sm:table-cell">
                                {city?.province_name_zh}
                              </TableCell>
                              <TableCell className="hidden text-right font-mono text-xs text-muted-foreground md:table-cell">
                                {Math.round(record.reliability * 100)}/100
                              </TableCell>
                              <TableCell className="text-right font-mono font-medium tabular-nums">
                                ¥{priceFormatter.format(record.median)}
                              </TableCell>
                              <TableCell className="text-right">
                                <Badge variant="secondary">{profile?.tier ?? '—'}</Badge>
                              </TableCell>
                            </TableRow>
                          );
                        })}
                      </TableBody>
                    </Table>
                  </div>
                  <div className="mt-3 grid gap-1 text-xs leading-5 text-muted-foreground sm:grid-cols-2">
                    <span>
                      高价省份（≥2 城市）：{provinceSummary[0]?.province ?? '样本不足'}{' '}
                      {provinceSummary[0] ? `¥${priceFormatter.format(provinceSummary[0].median)}` : ''}
                    </span>
                    <span>
                      低价省份（≥2 城市）：{provinceSummary.at(-1)?.province ?? '样本不足'}{' '}
                      {provinceSummary.at(-1)
                        ? `¥${priceFormatter.format(provinceSummary.at(-1)!.median)}`
                        : ''}
                    </span>
                  </div>
                </CardContent>
              </Card>

              <Card className="border-0 bg-card/94 shadow-[0_14px_44px_rgb(43_66_54/6%)] ring-1 ring-foreground/8">
                <CardHeader className="border-b border-border/65 pb-4">
                  <CardTitle>历史季节区间</CardTitle>
                  <CardDescription>
                    {currentCity?.city_name_zh}各历月的跨年中位数与四分位区间，仅描述 2014–2022 历史样本。
                  </CardDescription>
                  <CardAction>
                    <Badge variant="secondary">最多 {Math.max(...seasonalData.map((item) => item.sampleYears))} 年样本</Badge>
                  </CardAction>
                </CardHeader>
                <CardContent className="pt-4">
                  <ChartContainer config={chartConfig} className="h-[320px] w-full aspect-auto">
                    <AreaChart data={seasonalData} margin={{ left: 0, right: 8, top: 12, bottom: 0 }}>
                      <CartesianGrid vertical={false} strokeDasharray="3 5" />
                      <XAxis dataKey="month" axisLine={false} tickLine={false} tickMargin={8} />
                      <YAxis
                        axisLine={false}
                        tickLine={false}
                        tickMargin={8}
                        width={50}
                        tickFormatter={(value) => `¥${Number(value).toFixed(1)}`}
                        domain={['auto', 'auto']}
                      />
                      <ChartTooltip
                        content={
                          <ChartTooltipContent
                            labelFormatter={(_, payloadItems) => {
                              const row = payloadItems?.[0]?.payload;
                              return row ? `${row.month} · ${row.sampleYears} 年样本` : '';
                            }}
                          />
                        }
                      />
                      <Area
                        type="monotone"
                        dataKey="p75"
                        stroke="transparent"
                        fill="var(--color-p75)"
                        fillOpacity={0.18}
                        isAnimationActive={false}
                      />
                      <Area
                        type="monotone"
                        dataKey="p25"
                        stroke="transparent"
                        fill="var(--card)"
                        fillOpacity={1}
                        isAnimationActive={false}
                      />
                      <Line
                        type="monotone"
                        dataKey="median"
                        stroke="var(--color-median)"
                        strokeWidth={2.4}
                        dot={{ r: 2.5, fill: 'var(--card)', strokeWidth: 2 }}
                        activeDot={{ r: 4 }}
                        isAnimationActive={false}
                      />
                      {selectedCalendarMonth && (
                        <ReferenceLine
                          x={selectedCalendarMonth}
                          stroke="var(--chart-3)"
                          strokeDasharray="4 4"
                          strokeWidth={1.5}
                        />
                      )}
                    </AreaChart>
                  </ChartContainer>
                  <div className="mt-3 grid gap-2 border-t border-border/65 pt-3 sm:grid-cols-2">
                    <div className="rounded-lg bg-rose-50 p-3 text-rose-900 ring-1 ring-rose-100">
                      <p className="text-[10px] font-semibold uppercase tracking-[0.12em]">历史高位月</p>
                      <p className="mt-1 font-medium">
                        {seasonalHigh?.month ?? '—'} · ¥
                        {seasonalHigh ? priceFormatter.format(seasonalHigh.median) : '—'}/kg
                      </p>
                    </div>
                    <div className="rounded-lg bg-emerald-50 p-3 text-emerald-900 ring-1 ring-emerald-100">
                      <p className="text-[10px] font-semibold uppercase tracking-[0.12em]">历史低位月</p>
                      <p className="mt-1 font-medium">
                        {seasonalLow?.month ?? '—'} · ¥
                        {seasonalLow ? priceFormatter.format(seasonalLow.median) : '—'}/kg
                      </p>
                    </div>
                  </div>
                  <p className="mt-3 text-xs leading-5 text-muted-foreground">
                    季节曲线按每个历月的年度观测汇总，不是未来预测；月份差异可能同时受供给、市场结构和数据覆盖影响。
                  </p>
                </CardContent>
              </Card>
            </div>

            <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1.18fr)_minmax(320px,0.82fr)]">
              <Card className="border-0 bg-card/94 shadow-[0_14px_44px_rgb(43_66_54/6%)] ring-1 ring-foreground/8">
                <CardHeader className="border-b border-border/65 pb-4">
                  <CardTitle>来源质量与覆盖</CardTitle>
                  <CardDescription>
                    质量状态与价格同屏；这里沿用 P0 的可靠性、日级质量与覆盖 Tier，不重新定义规则。
                  </CardDescription>
                  <CardAction>
                    <Badge variant="secondary">Tier {currentProfile?.tier ?? '—'}</Badge>
                  </CardAction>
                </CardHeader>
                <CardContent className="space-y-5 pt-4">
                  <div className="grid gap-4 sm:grid-cols-2">
                    <Progress value={selectedRecord.reliability * 100}>
                      <ProgressLabel className="flex items-center gap-1.5 text-xs">
                        <CircleGauge className="size-3.5 text-primary" aria-hidden="true" />
                        当月平均可靠性
                      </ProgressLabel>
                      <ProgressValue>
                        {() => `${Math.round(selectedRecord.reliability * 100)} / 100`}
                      </ProgressValue>
                    </Progress>
                    <Progress value={(currentProfile?.coverageRate ?? 0) * 100}>
                      <ProgressLabel className="flex items-center gap-1.5 text-xs">
                        <Database className="size-3.5 text-primary" aria-hidden="true" />
                        全期有效日覆盖
                      </ProgressLabel>
                      <ProgressValue>
                        {() => `${Math.round((currentProfile?.coverageRate ?? 0) * 100)}%`}
                      </ProgressValue>
                    </Progress>
                  </div>

                  <div>
                    <div className="mb-2 flex items-center justify-between gap-3 text-xs">
                      <span className="font-medium">当月日级质量构成</span>
                      <span className="text-muted-foreground">
                        {selectedRecord.validDays}/{daysInMonth(selectedRecord.month)} 个自然日有观测
                      </span>
                    </div>
                    <div
                      className="flex h-2.5 w-full overflow-hidden rounded-full bg-muted"
                      aria-label={`good ${selectedRecord.goodDays} 天，caution ${selectedRecord.cautionDays} 天，poor ${selectedRecord.poorDays} 天`}
                    >
                      <span
                        className="bg-emerald-600"
                        style={{ width: `${(selectedRecord.goodDays / selectedRecord.validDays) * 100}%` }}
                      />
                      <span
                        className="bg-amber-500"
                        style={{ width: `${(selectedRecord.cautionDays / selectedRecord.validDays) * 100}%` }}
                      />
                      <span
                        className="bg-rose-500"
                        style={{ width: `${(selectedRecord.poorDays / selectedRecord.validDays) * 100}%` }}
                      />
                    </div>
                    <div className="mt-2 grid grid-cols-3 gap-2 text-xs">
                      <span className="flex items-center gap-1.5 text-emerald-800">
                        <i className="size-2 rounded-full bg-emerald-600" aria-hidden="true" />
                        good {selectedRecord.goodDays} 天
                      </span>
                      <span className="flex items-center gap-1.5 text-amber-800">
                        <i className="size-2 rounded-full bg-amber-500" aria-hidden="true" />
                        caution {selectedRecord.cautionDays} 天
                      </span>
                      <span className="flex items-center gap-1.5 text-rose-800">
                        <i className="size-2 rounded-full bg-rose-500" aria-hidden="true" />
                        poor {selectedRecord.poorDays} 天
                      </span>
                    </div>
                  </div>

                  <div className="grid gap-2 text-xs sm:grid-cols-4">
                    <div className="rounded-lg border border-border/70 p-3">
                      <p className="text-muted-foreground">月度日覆盖</p>
                      <p className="mt-1 font-mono font-medium tabular-nums">
                        {Math.round(selectedMonthCoverage * 100)}%
                      </p>
                    </div>
                    <div className="rounded-lg border border-border/70 p-3">
                      <p className="text-muted-foreground">报告市场中位数</p>
                      <p className="mt-1 font-mono font-medium tabular-nums">
                        {selectedRecord.medianMarkets.toFixed(1)}
                      </p>
                    </div>
                    <div className="rounded-lg border border-border/70 p-3">
                      <p className="text-muted-foreground">报告市场最大值</p>
                      <p className="mt-1 font-mono font-medium tabular-nums">
                        {selectedRecord.maxMarkets}
                      </p>
                    </div>
                    <div className="rounded-lg border border-border/70 p-3">
                      <p className="text-muted-foreground">全期有效日</p>
                      <p className="mt-1 font-mono font-medium tabular-nums">
                        {integerFormatter.format(currentProfile?.totalValidDays ?? 0)}
                      </p>
                    </div>
                  </div>

                  {(selectedRecord.poorDays > 0 || selectedRecord.medianMarkets <= 1) && (
                    <Alert className="border-amber-200 bg-amber-50 text-amber-950">
                      <CircleAlert />
                      <AlertTitle>解释这条价格时需要保留谨慎</AlertTitle>
                      <AlertDescription className="text-amber-900/80">
                        {selectedRecord.poorDays > 0
                          ? `本月有 ${selectedRecord.poorDays} 个观测日被 P0 标为 poor。`
                          : ''}{' '}
                        {selectedRecord.medianMarkets <= 1
                          ? '月内典型观测只来自 1 个报告市场，城市代表性有限。'
                          : ''}
                      </AlertDescription>
                    </Alert>
                  )}
                </CardContent>
              </Card>

              <Card className="border-0 bg-[linear-gradient(145deg,color-mix(in_oklab,var(--primary)_8%,var(--card)),var(--card))] shadow-[0_14px_44px_rgb(43_66_54/6%)] ring-1 ring-foreground/8">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Info className="size-4 text-primary" aria-hidden="true" />
                    如何使用这组信号
                  </CardTitle>
                  <CardDescription>把价格相对位置与来源条件一起读。</CardDescription>
                </CardHeader>
                <CardContent className="space-y-4 text-sm leading-6">
                  <div>
                    <p className="font-medium">可以回答</p>
                    <p className="mt-1 text-muted-foreground">
                      这个城市在所选历史月份的价格水平、相对排名、月内波动和历史季节位置。
                    </p>
                  </div>
                  <div>
                    <p className="font-medium">不能直接推出</p>
                    <p className="mt-1 text-muted-foreground">
                      当前市场报价、成交量、规格差异、运输成本或某地价格更高的因果原因。
                    </p>
                  </div>
                  <div className="rounded-lg border border-border/70 bg-background/65 p-3">
                    <p className="font-medium">当前产品覆盖边界</p>
                    <p className="mt-1 text-muted-foreground">
                      Tier A/B 默认可比较 {currentProduct?.monitor_eligible_city_count ?? 0} 个城市；Tier C{' '}
                      {currentProduct?.tier_counts.C ?? 0} 个组合不进入默认排名，但仍保留在数据资产中。
                    </p>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Tier 原因：{currentProfile?.tierReason ?? '未提供'}
                  </p>
                </CardContent>
              </Card>
            </div>

            <footer className="mt-4 flex flex-col gap-1 border-t border-border/60 py-4 text-xs leading-5 text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
              <span>历史回放，不构成当前报价或采购建议。</span>
              <span>数据窗口：2014-02-02—2022-06-22 · 最后完整月份：2022-05</span>
            </footer>
          </section>
        )}
      </div>
    </main>
  );
}
